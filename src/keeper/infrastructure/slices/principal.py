"""MCP tool-handler principal resolver.

Every MCP tool's `register()` closure calls `get_mcp_principal_id(ctx)`
to resolve the calling principal's UUID, mirroring the HTTP-side
`keeper.infrastructure.request.get_principal_id` 3-mode logic at the
MCP boundary.

Three modes, in priority order:

  1. **Bearer-auth mode + valid bearer**:
     `BearerAuthMiddleware` verified an `Authorization: Bearer <token>`
     against the MCP Surface audience (the middleware applies to
     both REST and `/mcp/*`) and stashed the `VerifiedPrincipal` on
     the Starlette `request.state.principal`. FastMCP keeps the same
     Starlette `Request` reachable via
     `ctx.request_context.request`; we read through.

  2. **Bearer-auth mode + no bearer**:
     No verified principal on request.state. Raise
     `McpUnauthenticatedError`; FastMCP wraps it as a structured
     `isError: true` JSON-RPC response. The legacy SYSTEM fallback
     is NOT allowed under bearer-auth mode (matches HTTP Mode 2).

  3. **Legacy mode** (no IdPs configured):
     Return `SYSTEM_PRINCIPAL_ID`. Mirrors HTTP's `X-Principal-Id`-
     absent path; reachable only when `require_authenticated_principal`
     is False (dev / test posture). Production deployments configure
     IdPs and run with the flag on.

Lives at `aroc/infrastructure/` (sibling to `request.py`) because
A BC's MCP tool modules consume it; per tach, BCs may depend on
`keeper.infrastructure` but NOT `keeper.api`. Importing FastMCP's
`Context` here is fine, the SDK is a leaf dependency, not part
of AROC's BC layer. Tools call through this helper rather than
reaching into `ctx.request_context.request.state` directly so the
3-mode logic stays in exactly one place.

`ctx` is typed `Any` at this boundary on purpose: FastMCP's `Context`
is generic over server-session / lifespan / request type parameters
and the SDK populates concrete types from the streamable-http
transport at runtime. Pinning the concrete generic parameters here
would couple the resolver to SDK-internal type variables that don't
have a stable public re-export. The 3-mode logic is structural and
defensive (every attribute access is wrapped); the contract-tier
tests pin the live SDK shape end-to-end.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from keeper.shared.reserved_ids import SYSTEM_PRINCIPAL_ID

if TYPE_CHECKING:
    from uuid import UUID


class McpUnauthenticatedError(Exception):
    """Raised when an MCP tool is invoked under bearer-auth mode with
    no verified principal on the request state.

    FastMCP wraps tool-handler exceptions as structured
    `isError: true` JSON-RPC responses; the client sees the message
    in `result.content[0].text`. The message is operator-friendly
    and points at the same RFC 9728 metadata endpoint the HTTP-side
    401 challenge does, so MCP clients can discover the IdP the same
    way HTTP clients do.
    """


def get_mcp_principal_id(ctx: Any) -> UUID:
    """Resolve the calling principal's UUID for an MCP tool handler.

    See module docstring for the 3-mode priority. `ctx` is the
    FastMCP `Context` injected into tool functions whose signature
    declares a `Context`-typed parameter.
    """
    request = _starlette_request_from_ctx(ctx)
    principal = _verified_principal(request)
    if principal is not None:
        return principal.principal_id

    if _bearer_auth_enabled(request):
        raise McpUnauthenticatedError(
            "Missing or invalid Authorization: Bearer token for MCP. "
            "This deployment requires a verified bearer token; see "
            "/.well-known/oauth-protected-resource for issuer metadata."
        )

    return SYSTEM_PRINCIPAL_ID


def _starlette_request_from_ctx(ctx: Any) -> Any:
    """Pull the Starlette Request off the FastMCP Context.

    `ctx.request_context.request` is set by FastMCP's streamable-http
    transport (see `mcp.server.streamable_http` in the python-sdk);
    it IS the same Starlette `Request` that `BearerAuthMiddleware`
    stashed on. In stdio transport there is no HTTP request, so
    `request` is None, stdio is not bearer-verified per
    this is deliberate.
    """
    try:
        return ctx.request_context.request
    except AttributeError:
        return None


def _verified_principal(request: Any) -> Any:
    """Return `request.state.principal` if a `VerifiedPrincipal`, else None.

    isinstance guard prevents a future middleware that accidentally
    writes a duck-typed object with a `.principal_id` attribute from
    silently authenticating callers (mirrors HTTP-side
    `_bearer_principal_id` ).
    """
    if request is None:
        return None
    from keeper.infrastructure.ports import VerifiedPrincipal

    try:
        principal = request.state.principal
    except AttributeError:
        return None
    if not isinstance(principal, VerifiedPrincipal):
        return None
    return principal


def _bearer_auth_enabled(request: Any) -> bool:
    """Return True when the deployment has a TokenVerifier configured.

    Mirrors the HTTP-side `_bearer_auth_enabled` in
    `keeper.infrastructure.request`. Reads through the same
    `app.state.deps` surface; equivalent shape on both transports.
    """
    if request is None:
        return False
    try:
        deps = request.app.state.deps
    except AttributeError:
        return False
    if deps is None:
        return False
    return deps.token_verifier is not None


__all__ = ["McpUnauthenticatedError", "get_mcp_principal_id"]
