"""The chassis serves its operational surfaces and nothing else.

These are the contract tests the baseline can actually make: the app boots,
both probes answer, metrics and the auth-discovery document are reachable, and
the OpenAPI document carries no domain. The last one is the interesting
assertion. It is what turns "we have not modelled anything yet" from a claim
into a check, so the first route that lands has to be added here deliberately.
"""

from typing import NoReturn, cast

import pytest
from fastapi.testclient import TestClient

from keeper.api.main import create_app
from keeper.infrastructure.auth.config import IdpConfig
from keeper.infrastructure.settings import Settings
from keeper.shared.reserved_ids import SYSTEM_HTTP_SURFACE_ID

pytestmark = pytest.mark.contract

EXPECTED_OPENAPI_PATHS = frozenset(
    {
        "/health",
        "/policies",
        "/policies/{policy_id}",
        "/policies/{policy_id}/permissions",
        "/policies/{policy_id}/permissions/{principal_id}/{command_name}",
        "/actors",
        "/actors/{actor_id}",
        "/actors/{actor_id}/deactivate",
        "/actors/{actor_id}/reactivate",
        "/datasets",
        "/datasets/{dataset_id}",
        "/proposals",
        "/proposals/{proposal_id}",
        "/proposals/{proposal_id}/take",
        "/devices",
        "/devices/{device_id}",
        "/devices/{device_id}/fault",
        "/devices/{device_id}/recover",
        "/devices/{device_id}/retire",
        "/plans",
        "/plans/{plan_id}",
        "/procedures",
        "/procedures/{procedure_id}",
        "/executions",
        "/executions/{execution_id}",
        "/executions/{execution_id}/steps",
        "/executions/{execution_id}/steps/{step_id}/run",
        "/executions/{execution_id}/claim",
        "/executions/{execution_id}/end",
        "/.well-known/oauth-protected-resource",
    }
)
"""Every path the application publishes in its OpenAPI document.

`/readyz` and `/metrics` are absent deliberately: both are registered with
`include_in_schema=False` because they are operational endpoints, not part of
the API anyone codes against.

A slice adding or retiring a route fails this test. That is the intent: the
change should be visible in a diff rather than absorbed silently.
"""


class _RefusingPool:
    """A pool whose every acquire is refused, standing in for a dead host."""

    def acquire(self, *, timeout: float | None = None) -> NoReturn:
        _ = timeout
        raise ConnectionRefusedError


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app(settings=Settings(app_env="test")))


def test_health_returns_ok_without_touching_any_dependency(client: TestClient) -> None:
    with client:
        response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "version" in body


def test_readyz_reports_ready_with_no_pool_in_test_mode(client: TestClient) -> None:
    with client:
        response = client.get("/readyz")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    # `skipped`, not `ok`: test mode builds no pool, and the probe says so
    # rather than reporting a healthy database that does not exist.
    assert body["database"] == "skipped"
    assert body["app_env"] == "test"
    assert body["schema"] == "matched"


def test_metrics_endpoint_counts_a_served_request(client: TestClient) -> None:
    with client:
        client.get("/health")
        response = client.get("/metrics")
    assert response.status_code == 200
    # /health is deliberately NOT in excluded_handlers: it is the sample
    # request that proves instrumentation is actually live, rather than
    # merely mounted.
    assert "/health" in response.text


def test_the_published_openapi_paths_match_the_pinned_set(client: TestClient) -> None:
    with client:
        response = client.get("/openapi.json")
    assert response.status_code == 200
    paths = frozenset(response.json()["paths"])
    assert paths == EXPECTED_OPENAPI_PATHS, (
        f"OpenAPI paths changed.\nAdded: {sorted(paths - EXPECTED_OPENAPI_PATHS)}\n"
        f"Removed: {sorted(EXPECTED_OPENAPI_PATHS - paths)}\n"
        "Update EXPECTED_OPENAPI_PATHS deliberately when a slice lands or "
        "retires a route."
    )


def test_protected_resource_metadata_is_discoverable(client: TestClient) -> None:
    with client:
        response = client.get("/.well-known/oauth-protected-resource")
    assert response.status_code == 200


def test_oversized_request_body_is_rejected_with_413(client: TestClient) -> None:
    """The body-size cap runs before anything reads the body."""
    settings = Settings(app_env="test")
    oversized = b"x" * (settings.max_request_body_size_bytes + 1)
    with client:
        response = client.post("/health", content=oversized)
    assert response.status_code == 413
    assert "exceeds limit" in response.json()["detail"]


EXPECTED_MIDDLEWARE_ORDER = (
    "PrometheusInstrumentatorMiddleware",
    "BodySizeLimitMiddleware",
    "BearerAuthMiddleware",
)
"""The assembled middleware stack, outermost first.

Pinned because the source cannot be read in execution order. Starlette
prepends each `add_middleware` call, so the last one added runs first and the
registration block reads backwards. The comment there once claimed the size
cap ran before token verification when it ran after, and nothing caught it.

The order itself is load-bearing: rejecting an oversized body must cost a
Content-Length comparison rather than a token introspection round trip to an
IdP, so `BodySizeLimitMiddleware` has to sit outside `BearerAuthMiddleware`.
"""


def test_middleware_runs_size_limit_before_token_verification() -> None:
    app = create_app(settings=Settings(app_env="test"))
    # Starlette types `Middleware.cls` as a factory protocol rather than a
    # class, so the class name is not reachable through the declared type.
    installed = tuple(cast("type", m.cls).__name__ for m in app.user_middleware)
    assert installed == EXPECTED_MIDDLEWARE_ORDER


def test_readyz_returns_503_and_retry_after_when_a_dependency_is_down() -> None:
    """The not-ready path end to end: status line, Retry-After, and body.

    `readiness_body` is unit-tested, but nothing asserted that a `not_ready`
    body actually changes the HTTP response. A probe that always answers 200
    with `"status": "not_ready"` in the payload reads as healthy to every
    orchestrator, which is the failure this pins.

    The pool is swapped for one that refuses rather than the environment being
    bent, so the route, the probe and the status mapping all run for real.
    """
    app = create_app(settings=Settings(app_env="test"))
    with TestClient(app) as client:
        object.__setattr__(app.state.deps, "pool", _RefusingPool())
        response = client.get("/readyz")
    assert response.status_code == 503
    assert response.headers["Retry-After"] == "5"
    assert response.json()["status"] == "not_ready"
    assert response.json()["database"] == "unreachable"


def test_metadata_resource_honors_the_reverse_proxy_headers(client: TestClient) -> None:
    """Production always sits behind a proxy, so the inbound URL is internal.

    Without the forwarded headers the `resource` field advertises something
    like `http://internal-pod-name:8000`, which no client can reach and which
    silently breaks auth discovery rather than erroring.
    """
    with client:
        response = client.get(
            "/.well-known/oauth-protected-resource",
            headers={"X-Forwarded-Proto": "https", "X-Forwarded-Host": "keeper.example"},
        )
    assert response.json()["resource"] == "https://keeper.example"


def test_metadata_resource_falls_back_to_the_request_url_without_a_proxy(
    client: TestClient,
) -> None:
    with client:
        response = client.get("/.well-known/oauth-protected-resource")
    assert response.json()["resource"] == "http://testserver"


def test_metadata_sets_a_max_age_so_clients_do_not_poll(client: TestClient) -> None:
    with client:
        response = client.get("/.well-known/oauth-protected-resource")
    assert "max-age" in response.headers["cache-control"]


def test_metadata_advertises_the_audience_of_each_configured_surface() -> None:
    """The route inverts `Settings.identity_providers` into a per-surface map.

    That inversion is where a surface can silently pick up the wrong audience,
    or none, and a client that requests the wrong audience gets a token the
    resource server will refuse with no clue why. Nothing else exercises it:
    the default test settings configure no provider at all.
    """
    settings = Settings(
        app_env="test",
        identity_providers=(
            IdpConfig(
                issuer="https://idp.example",
                audiences={SYSTEM_HTTP_SURFACE_ID: "aud-http"},
                jwks_url="https://idp.example/jwks",
            ),
        ),
    )
    with TestClient(create_app(settings=settings)) as client:
        document = client.get("/.well-known/oauth-protected-resource").json()
    assert document["authorization_servers"] == ["https://idp.example"]
    assert document["io.keeper.surface_audiences"] == {"http": "aud-http"}
    assert document["aud_values_supported"] == ["aud-http"]
