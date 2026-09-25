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


@pytest.mark.parametrize("env", ["prod", "production", "staging"])
def test_production_tier_environments_are_recognised(env: str) -> None:
    """Staging counts: it usually holds real data and is reachable."""
    assert Settings(app_env=env).is_production_tier


@pytest.mark.parametrize("env", ["local", "test", "dev"])
def test_non_production_environments_are_not_production_tier(env: str) -> None:
    assert not Settings(app_env=env).is_production_tier
