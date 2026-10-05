"""Settings validation: a misconfiguration fails at startup, not at first use."""

import re

import pytest
from pydantic import ValidationError

from keeper.infrastructure.settings import Settings

pytestmark = pytest.mark.unit


def test_database_url_with_a_sqlalchemy_driver_prefix_is_rejected() -> None:
    """A SQLAlchemy driver prefix is not something asyncpg accepts, and it fails late."""
    with pytest.raises(ValidationError, match="DATABASE_URL must start with"):
        Settings(app_env="test", database_url="postgresql+psycopg2://a:b@localhost/db")


def test_otel_sampler_ratio_outside_the_unit_interval_is_rejected() -> None:
    with pytest.raises(ValidationError, match=re.escape("must be in [0.0, 1.0]")):
        Settings(app_env="test", otel_sampler_ratio=1.5)


def test_projection_poll_interval_below_the_floor_is_rejected() -> None:
    """Below 100ms the worker tight-loops, which reads as a hang, not a setting."""
    with pytest.raises(ValidationError, match=re.escape("must be >= 0.1")):
        Settings(app_env="test", projection_poll_interval_seconds=0.01)


def test_idempotency_lock_stale_seconds_below_one_is_rejected() -> None:
    """Under a second, every concurrent claim looks stale and the guard turns off."""
    with pytest.raises(ValidationError, match=re.escape("must be >= 1")):
        Settings(app_env="test", idempotency_lock_stale_seconds=0)


def test_negative_idempotency_ttl_is_rejected_while_zero_disables_the_pruner() -> None:
    assert Settings(app_env="test", idempotency_ttl_hours=0).idempotency_ttl_hours == 0
    with pytest.raises(ValidationError, match=re.escape("must be >= 0")):
        Settings(app_env="test", idempotency_ttl_hours=-1)


@pytest.mark.parametrize("env", ["prod", "production", "staging", "pilot", "whatever"])
def test_an_environment_outside_the_development_list_is_a_production_tier(env: str) -> None:
    """Including `whatever`, which is the property rather than an oddity.

    The tier is decided by exclusion, so a name nothing has agreed is
    gated instead of exempt. Staging and pilot are here because both hold
    real data; the last one is here because neither did when the question
    was which names to enumerate.
    """
    assert Settings(app_env=env).is_production_tier


@pytest.mark.parametrize("env", ["local", "test", "dev", "LOCAL", "Dev"])
def test_a_development_environment_is_not_a_production_tier(env: str) -> None:
    """Case folded, so a capitalised .env does not quietly arm the gates."""
    assert not Settings(app_env=env).is_production_tier
