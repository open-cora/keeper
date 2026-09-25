"""RFC 9728 Protected Resource Metadata endpoint.

MCP spec 2025-11-25 (basic/authorization) mandates that OAuth-2.1
resource servers expose a Protected Resource Metadata document at
`/.well-known/oauth-protected-resource`. Clients GET this to
discover which authorization servers issue tokens for which
resources (per-Surface audience identifiers), what scopes are
supported, and what token formats are accepted.

The keeper's RFC 9728 document is generated from
`Settings.identity_providers` + the 3 SYSTEM Surface audience
identifiers: no DB, no auth, just config-driven JSON.

The 401 `WWW-Authenticate` header that the edge middleware returns
includes `resource_metadata="https://<deployment>/.well-known/oauth-protected-resource"`
so clients can fetch this document programmatically on first-401
and discover where to obtain a fresh token.

## What's NOT here

  - The `authorization_servers_metadata` linked documents. Those
    live at the IdP's `/.well-known/oauth-authorization-server`,
    which IS the IdP's responsibility per RFC 8414. The keeper's RFC 9728
    only POINTS to them via `authorization_servers: [<issuer URL>,
    ...]`.
  - Per-tenant fan-out (different Surface IDs per tenant), deferred
    by design.
"""

from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from keeper.infrastructure.auth.config import IdpConfig
from keeper.shared.reserved_ids import (
    SYSTEM_HTTP_SURFACE_ID,
    SYSTEM_MCP_STDIO_SURFACE_ID,
    SYSTEM_MCP_STREAMABLE_HTTP_SURFACE_ID,
)


def build_protected_resource_metadata(
    *,
    resource: str,
    identity_providers: list[IdpConfig],
    surface_audiences: dict[str, str | None],
) -> dict[str, Any]:
    """Build the RFC 9728 document body.

    Four standard keys and one extension. `resource` is the deployment's
    canonical base URL, `authorization_servers` the sorted issuer list a
    client dereferences to RFC 8414 metadata, `bearer_methods_supported`
    the fixed `["header"]`, and `aud_values_supported` every configured
    audience so a client knows which to request.

    A surface is not a sub-resource. RFC 9728 has no field for "the same
    resource reached three ways, each wanting a different audience", so the
    per-surface map goes in the extension key rather than being forced into
    a standard one that means something else. A client that ignores the
    extension still gets a usable document; it just has to pick from
    `aud_values_supported` without being told which surface each belongs to.

    `surface_audiences` values of `None` mean no IdP is registered for that
    surface, and those entries are dropped rather than emitted as nulls: an
    absent key says "not configured" in a way a null does not.
    """
    issuers = sorted({str(idp.issuer) for idp in identity_providers})
    aud_values = [v for v in surface_audiences.values() if v]
    document: dict[str, Any] = {
        "resource": resource,
        "authorization_servers": issuers,
        "bearer_methods_supported": ["header"],
    }
    if aud_values:
        document["aud_values_supported"] = sorted(set(aud_values))
    # Per-Surface audience map as a non-standard but namespaced keeper
    # extension. An `x-` prefix was considered first; per
    # RFC 6648 (2012) the `X-`/`x-` convention is deprecated across
    # IETF protocols and RFC 9728 itself doesn't reserve `x-` keys.
    # Reverse-
    # DNS namespacing (`io.keeper.surface_audiences`) matches the JSON-
    # Schema / OAuth-2.0 extension conventions and avoids both the
    # deprecated prefix and accidental collision with future RFC 9728
    # registered keys.
    document["io.keeper.surface_audiences"] = {
        name: aud for name, aud in surface_audiences.items() if aud is not None
    }
    return document


def register_protected_resource_metadata_route(app: FastAPI) -> None:
    """Mount `GET /.well-known/oauth-protected-resource` on the app.

    The handler reads `app.state.deps.settings.identity_providers`
    at request time so re-deploys with a new identity-provider list
    take effect on next request (no app restart needed for config
    rotation, provided the lifespan re-loaded Settings, which it
    doesn't today; this is a forward-looking handler shape).
    """

    @app.get(
        "/.well-known/oauth-protected-resource",
        tags=["edge-auth"],
        summary="RFC 9728 Protected Resource Metadata",
    )
    async def protected_resource_metadata(  # pyright: ignore[reportUnusedFunction]
        request: Request,
    ) -> JSONResponse:
        settings = request.app.state.deps.settings
        # Build a per-Surface audience map by inverting the
        # identity_providers list. When multiple IdPs declare the
        # same Surface, the audience strings must agree (it's the
        # SAME resource URL) so the values collapse cleanly.
        surface_name_by_uuid = {
            SYSTEM_HTTP_SURFACE_ID: "http",
            SYSTEM_MCP_STDIO_SURFACE_ID: "mcp_stdio",
            SYSTEM_MCP_STREAMABLE_HTTP_SURFACE_ID: "mcp_streamable_http",
        }
        surface_audiences: dict[str, str | None] = {
            name: None for name in surface_name_by_uuid.values()
        }
        for idp in settings.identity_providers:
            for surface_uuid, aud_str in idp.audiences.items():
                name = surface_name_by_uuid.get(surface_uuid)
                if name is not None:
                    surface_audiences[name] = aud_str

        # Resource identifier: scheme + host of the inbound request,
        # no path. Per RFC 9728 §3.1 the resource value SHOULD be the
        # canonical URL of the resource server. Honor standard reverse-
        # proxy headers (X-Forwarded-Proto + X-Forwarded-Host) because
        # a production keeper always sits behind one (Cloudflare / nginx /
        # IAP). Without this, the `resource` field reads
        # `http://internal-pod-name:8000` instead of the public URL
        # and clients can't discover the auth flow correctly.
        #
        scheme = request.headers.get("x-forwarded-proto", request.url.scheme)
        host = request.headers.get("x-forwarded-host", request.url.netloc)
        resource = f"{scheme}://{host}"

        document = build_protected_resource_metadata(
            resource=resource,
            identity_providers=list(settings.identity_providers),
            surface_audiences=surface_audiences,
        )
        # Cache-Control: clients SHOULD cache for the audience-
        # rotation window; 5 minutes balances "operator rotates IdPs"
        # vs "100 MCP clients hammering /.well-known/" on cold start.
        return JSONResponse(
            content=document,
            headers={"Cache-Control": "public, max-age=300"},
        )


__all__ = [
    "build_protected_resource_metadata",
    "register_protected_resource_metadata_route",
]
