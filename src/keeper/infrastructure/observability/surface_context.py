"""Bind the arrival Surface identity to structlog contextvars.

`BearerAuthMiddleware` resolves the arrival Surface UUID from the
request path (see `_resolve_expected_audience` in
`keeper.infrastructure.auth.bearer`) so the verifier can
audience-bind. The SAME identity is also a missing observability
dimension: every log line emitted inside the request body should carry
`surface_id` + `surface_kind` so operators can pivot from a single log
record to "which arrival surface produced this".

The two-pass model is intentional:

  - Domain pass (load-bearing): `surface_id` flows through handler
    function arguments and into `deps.authz.authorize(...)`. Authz
    reads from the function arg, NOT from structlog contextvars.
  - Observability pass (this module): structlog contextvars carry the
    same identity for every log line in the request. Pure-additive log
    dimension; does NOT replace the domain pass.

## Binding seam

The middleware calls `bind_surface_context` once per request (after
the unauthenticated-path skip, before any downstream work) and
`clear_surface_context` in a `finally` block. Same asyncio task =
same contextvars scope; the try/finally guarantees no leakage even
if a downstream handler raises.

## MCP_STDIO is intentionally out of scope here

stdio MCP servers do not flow through the HTTP middleware (separate
subprocess transport). Their observability binding would land at the
FastMCP server entrypoint, not here. The kind map below excludes
`SYSTEM_MCP_STDIO_SURFACE_ID` for that reason; an HTTP request that
somehow resolved to the stdio Surface is a deploy-time bug, not a
missing observability case.

## Why the kind values are local string literals

There is no authoritative `SurfaceKind` enum yet: no BC models an
ingress surface, so these literals are the only definition of the
vocabulary rather than a mirror of one.

That changes the moment a BC declares the enum. Infrastructure may not
import a BC (tach enforces it), so the literals here will then be a
COPY of that enum's `.value` strings, and a copy with no check drifts.
Add the fitness test that cross-checks the two at that point; until
there is a second definition there is nothing to cross-check, and a
test asserting these strings against themselves would agree by
construction.
"""

from uuid import UUID

import structlog

from keeper.shared.reserved_ids import SYSTEM_HTTP_SURFACE_ID, SYSTEM_MCP_STREAMABLE_HTTP_SURFACE_ID

__all__ = [
    "SURFACE_KIND_HTTP",
    "SURFACE_KIND_MCP_STREAMABLE_HTTP",
    "UnknownSurfaceError",
    "bind_surface_context",
    "clear_surface_context",
    "surface_kind_for",
]


SURFACE_KIND_HTTP = "http"
SURFACE_KIND_MCP_STREAMABLE_HTTP = "mcp_streamable_http"


class UnknownSurfaceError(LookupError):
    """Raised when a Surface UUID has no kind mapping.

    Loud-fail by design: a new Surface UUID seeded without an entry
    in `_SURFACE_KIND_BY_UUID` is a deploy-time bug. Silent fallback
    to a sentinel kind would let the observability dimension drift
    out of step with the seeded Surfaces.
    """


_SURFACE_KIND_BY_UUID: dict[UUID, str] = {
    SYSTEM_HTTP_SURFACE_ID: SURFACE_KIND_HTTP,
    SYSTEM_MCP_STREAMABLE_HTTP_SURFACE_ID: SURFACE_KIND_MCP_STREAMABLE_HTTP,
}
"""HTTP-reachable Surface UUID to kind-string map.

`SYSTEM_MCP_STDIO_SURFACE_ID` is intentionally absent: stdio MCP is a
subprocess transport, never reachable via the HTTP middleware. Any
future HTTP-reachable Surface (A2A, gRPC bridge, etc.) lands here
when its UUID is seeded.
"""


def surface_kind_for(surface_id: UUID) -> str:
    """Return the kind string for a known HTTP-reachable Surface UUID.

    Raises `UnknownSurfaceError` when the UUID is not in the map.
    The middleware passes the resolved expected-audience UUID, which
    today is always one of the two HTTP-reachable system Surfaces;
    a mismatch indicates the seed migration and this map drifted.
    """
    kind = _SURFACE_KIND_BY_UUID.get(surface_id)
    if kind is None:
        raise UnknownSurfaceError(
            f"No SurfaceKind mapping for surface_id={surface_id}. "
            "Add the UUID to _SURFACE_KIND_BY_UUID when a new Surface "
            "is seeded into HTTP-reachable routing."
        )
    return kind


def bind_surface_context(surface_id: UUID, surface_kind: str) -> None:
    """Bind `surface_id` + `surface_kind` to structlog contextvars.

    Stringifies the UUID so the structlog `JSONRenderer` emits stable,
    log-aggregator-indexable shapes. Pairs with `clear_surface_context()`
    in a `try/finally` at the middleware seam.
    """
    structlog.contextvars.bind_contextvars(
        surface_id=str(surface_id),
        surface_kind=surface_kind,
    )


def clear_surface_context() -> None:
    """Unbind `surface_id` + `surface_kind` from structlog contextvars.

    Called from the middleware's `finally` block so the binding never
    leaks across requests even when a downstream handler raises. Idempotent:
    safe to call when nothing was previously bound (structlog tolerates
    unbind of missing keys).
    """
    structlog.contextvars.unbind_contextvars("surface_id", "surface_kind")
