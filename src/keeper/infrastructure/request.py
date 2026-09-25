"""Who is calling, through which door, and under which correlation.

Four FastAPI dependencies resolve those three facts from the live
request, and the constants beside them are the answers used when the
request does not carry one:

  - `get_correlation_id`: the request's correlation UUID, taken from the
    active OTel span, or freshly minted when no span is active (tests
    run against the no-op tracer).
  - `get_principal_id`: the caller's UUID from the `X-Principal-Id`
    header, or `SYSTEM_PRINCIPAL_ID` when the deployment still allows an
    unauthenticated fallback. See `get_principal_id` for the three modes
    and which setting selects each.
  - `get_surface_id` / `get_mcp_surface_id`: which ingress the call
    arrived through, as one of the `SYSTEM_*_SURFACE_ID` constants.

These live in `keeper.infrastructure` rather than in `keeper.api` because
three kinds of caller need the same answers and none of them is a REST
route: the bearer-auth middleware, the MCP principal resolver in
`keeper.infrastructure.slices.principal`, and the envelope builders in
`keeper.infrastructure.slices`. A bounded context's routes will be the
fourth, and putting the resolvers in one of them would make the other
three reach across a boundary for a fact about the request they are
already holding.

Nothing here decides where a request goes. The module's previous name,
`routing`, promised that and delivered identity resolution instead.
"""

from typing import Annotated
from uuid import UUID

from fastapi import Depends, Header, HTTPException, Request, status
from pydantic import BaseModel

from keeper.infrastructure.observability import current_correlation_id
from keeper.shared.reserved_ids import (
    SYSTEM_HTTP_SURFACE_ID,
    SYSTEM_MCP_STREAMABLE_HTTP_SURFACE_ID,
    SYSTEM_PRINCIPAL_ID,
)


class ErrorResponse(BaseModel):
    """The body every error response carries.

    One field, so a client can render a failure without a per-endpoint
    branch. Declared here rather than per slice because the shape is the
    same whichever slice raised, and because a route's `responses=` needs
    something to name for OpenAPI to document the failure at all.
    """

    detail: str


def get_correlation_id() -> UUID:
    """Derive the request's correlation UUID from the active OTel span.

    OpenTelemetry is the source of truth for "this request" identity:
    `FastAPIInstrumentor` extracts the inbound W3C `traceparent` header
    (or starts a fresh trace when absent) and exposes the trace_id
    through the active span. `current_correlation_id` formats the
    128-bit trace_id as a UUID; if no span is active (test environments
    using the no-op tracer), it generates a fresh UUID.
    """
    return current_correlation_id()


def _require_authenticated_principal(request: Request) -> bool:
    """Read the `require_authenticated_principal` flag off the running
    app's settings (carried on the kernel attached to `app.state.deps`).

    Lives as its own Depends so `get_principal_id` stays testable in
    isolation and so the read happens at request time (the kernel
    isn't attached to app.state until the lifespan runs).
    """
    return bool(request.app.state.deps.settings.require_authenticated_principal)


def _bearer_principal_id(request: Request) -> UUID | None:
    """Return `request.state.principal.principal_id` if set, else None.

    `BearerAuthMiddleware` populates `request.state.principal` when
    an `Authorization: Bearer` header verified successfully.
    `get_principal_id` reads through this Depends so the existing
    in-isolation unit tests for `get_principal_id` keep working
    without a Request object.

    The `isinstance(principal, VerifiedPrincipal)` guard is the point
    of this helper. Today only `BearerAuthMiddleware` writes to
    `request.state.principal`, but a future middleware that
    accidentally writes a duck-typed object carrying a `.principal_id`
    attribute would silently authenticate callers. Pinning the type
    here closes that before it ships.
    """
    # Lazy import: matches the cycle-break pattern in
    # auth/bearer.py + auth/config.py.
    from keeper.infrastructure.ports import VerifiedPrincipal

    principal = getattr(request.state, "principal", None)
    if not isinstance(principal, VerifiedPrincipal):
        return None
    return principal.principal_id


def _bearer_auth_enabled(request: Request) -> bool:
    """Return True when `kernel.token_verifier` is non-None.

    `BearerAuthMiddleware` populates `request.state.principal` from a
    verified bearer when this is True. `get_principal_id` consults
    this to refuse X-Principal-Id fallback under bearer-auth mode
    (the cleartext header is unauthenticated in that posture, so
    accepting it would defeat the bearer gate).
    """
    deps = getattr(request.app.state, "deps", None)
    if deps is None:
        return False
    return deps.token_verifier is not None


def get_principal_id(
    x_principal_id: Annotated[
        UUID | None,
        Header(
            alias="X-Principal-Id",
            description=(
                "Legacy principal-id header (trust-the-proxy shape). "
                "When `Settings.identity_providers` is configured "
                "(bearer-auth mode), "
                "this header is IGNORED and the verified bearer token "
                "from `BearerAuthMiddleware` (Authorization: "
                "Bearer) sets the principal. When no IdPs are configured "
                "(legacy mode), the application TRUSTS this header (no "
                "cryptographic verification), so production deployments in "
                "legacy mode MUST front the API with an auth proxy that "
                "strips any client-supplied X-Principal-Id and sets it to "
                "the verified principal UUID. Behavior when absent: see "
                "Settings.require_authenticated_principal."
            ),
        ),
    ] = None,
    bearer_principal_id: Annotated[
        UUID | None,
        Depends(_bearer_principal_id),
    ] = None,
    bearer_auth_enabled: Annotated[
        bool,
        Depends(_bearer_auth_enabled),
    ] = False,
    require_authenticated: Annotated[
        bool,
        Depends(_require_authenticated_principal),
    ] = False,
) -> UUID:
    """Resolve the calling principal's id.

    Three modes, in priority order:

      1. **Bearer-auth mode + valid bearer**:
         `BearerAuthMiddleware` verified an `Authorization: Bearer
         <token>` and stashed the `VerifiedPrincipal` on
         `request.state.principal`. Return its
         `principal_id`. X-Principal-Id is silently IGNORED in this
         mode (cleartext header is unauthenticated; honoring it
         would defeat the bearer gate).

      2. **Bearer-auth mode + no bearer**:
         No verified principal on request.state. The middleware
         already let the request through (it doesn't impose a 401
         policy on its own). Refuse here with 401 -- the legacy
         X-Principal-Id fallback is NOT allowed under bearer-auth
         mode regardless of `require_authenticated_principal`.

      3. **Legacy mode** (no IdPs configured):
         - X-Principal-Id present -> use it.
         - Absent + `require_authenticated_principal=True` -> 401.
         - Absent + `require_authenticated_principal=False` ->
           SYSTEM_PRINCIPAL_ID fallback (legacy dev / test).
    """
    # Mode 1: bearer-verified principal wins unconditionally.
    if bearer_principal_id is not None:
        return bearer_principal_id

    # Mode 2: bearer-auth on but no bearer presented.
    if bearer_auth_enabled:
        # Format the challenge through the shared helper so the realm and
        # resource_metadata constants live in exactly one place. A rename
        # there then updates one site, not two. The lazy import matches the
        # cycle-break pattern used elsewhere in this module.
        from keeper.infrastructure.auth.exception_handlers import missing_bearer_challenge

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=(
                "Missing Authorization: Bearer header; this deployment "
                "requires a verified bearer token. See "
                "/.well-known/oauth-protected-resource for issuer metadata."
            ),
            headers={"WWW-Authenticate": missing_bearer_challenge()},
        )

    # Mode 3: legacy X-Principal-Id path.
    if x_principal_id is None:
        if require_authenticated:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=(
                    "Missing X-Principal-Id header; this deployment "
                    "requires an authenticated principal."
                ),
            )
        return SYSTEM_PRINCIPAL_ID
    return x_principal_id


def get_surface_id(request: Request) -> UUID:
    """Resolve the arrival Surface for an HTTP request.

    Returns a constant. The surface is derived from the process, never
    from a client-asserted header or query parameter, because a caller
    that could name its own arrival surface could choose which
    idempotency namespace to land in.

    `request` is unused today and still in the signature: the intended
    next step is to check the bearer token's `aud` claim against the
    surface's expected audience before returning, and adding the
    parameter later would change every call site's dependency wiring.
    """
    _ = request
    return SYSTEM_HTTP_SURFACE_ID


def get_mcp_surface_id() -> UUID:
    """Resolve the arrival Surface for an MCP tool call.

    AROC only serves MCP over streamable-http in production (per
    `aroc/api/main.py` mounting `streamable_http_app()`). Stdio is
    unreachable in production. The adapter returns the streamable-
    http constant unconditionally, no `ctx` parameter needed, so
    existing MCP tool signatures don't change.

    If stdio ships later, pin the surface id on a closure parameter at
    tool-registration time (`register(mcp, *, surface_id=...)`) rather
    than reading it off `ctx`. Both keep the rule that no surface is
    client-asserted; the closure keeps it without trusting a field the
    client populates.
    """
    return SYSTEM_MCP_STREAMABLE_HTTP_SURFACE_ID


__all__ = [
    "ErrorResponse",
    "get_correlation_id",
    "get_mcp_surface_id",
    "get_principal_id",
    "get_surface_id",
]
