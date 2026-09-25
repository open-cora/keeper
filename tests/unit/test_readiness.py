"""Readiness rendering: the vocabulary is fixed and the body leaks nothing."""

import pytest

from keeper.api._readiness import readiness_body
from keeper.infrastructure.settings import Settings

pytestmark = pytest.mark.unit


def test_readiness_body_reports_ready_when_the_database_probe_is_skipped() -> None:
    body = readiness_body("skipped", Settings(app_env="test"))
    assert body["status"] == "ready"


def test_readiness_body_reports_not_ready_when_the_database_is_unreachable() -> None:
    body = readiness_body("unreachable", Settings(app_env="local"))
    assert body["status"] == "not_ready"
    assert body["database"] == "unreachable"


def test_readiness_body_reports_ready_despite_a_degraded_schema() -> None:
    """A degraded process serves reads correctly, which is why it was allowed to boot.

    Reporting it unready would have an orchestrator pull it from rotation and
    remove the very access the override existed to grant.
    """
    body = readiness_body("ok", Settings(app_env="local"), "degraded")
    assert body["status"] == "ready"
    assert body["schema"] == "degraded"


def test_readiness_body_omits_the_database_url_and_error_text() -> None:
    """The endpoint is unauthenticated; the body must describe nothing."""
    settings = Settings(app_env="local", database_url="postgresql://secret:pw@db.internal/x")
    body = readiness_body("unreachable", settings)
    rendered = " ".join(body.values())
    assert "secret" not in rendered
    assert "db.internal" not in rendered
    assert "pw" not in rendered
