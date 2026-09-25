"""Read the routed request path from the ASGI scope.

## Why this helper exists

`request.url.path` is reconstructed by Starlette by concatenating
`http://{Host header}{path}` and re-parsing. CVE-2026-48710 (the
"badhost" advisory, published 2026-06-04, CVSS 6.5) shows that a
malformed `Host` header containing `/`, `?`, or `#` shifts the
path/query/fragment boundaries during re-parsing, so the parsed
`request.url.path` no longer matches the path the router actually
dispatched on. Middleware that reads `request.url.path` for security
decisions can be bypassed; the router still hands off to the original
endpoint because it reads the raw ASGI scope path.

Affected Starlette versions: `<= 1.0.0`. We pin `0.52.1` transitively
via FastAPI `>=0.136.1,<0.137`, which does not yet accept Starlette
`1.0.1`. Upgrading the library is a separate, larger project.

## What this fixes

`request.scope["path"]` is the raw routed path Starlette extracted
from the ASGI scope before any URL reconstruction. It is the same
value the router itself uses, so middleware reading it cannot
disagree with the dispatched endpoint regardless of `Host` header
contents.

All security-sensitive auth code in this package MUST call
`_routed_path(request)` instead of `request.url.path`. Forensic
logging in this package follows the same convention for
consistency: the logged path then always matches the routed path,
removing one source of post-incident confusion.

`Request.url.scheme` / `Request.url.netloc` / `Request.url.query`
are still Host-reconstructed and remain at the call site's
discretion; the badhost class only desyncs the path component.
"""

from typing import cast

from starlette.requests import Request


def _routed_path(request: Request) -> str:
    """Return the routed request path from the ASGI scope.

    See module docstring for the CVE-2026-48710 background. Use
    this instead of `request.url.path` for any decision the auth
    middleware makes; the two values diverge under a crafted
    `Host` header on vulnerable Starlette versions.
    """
    return cast("str", request.scope["path"])


__all__ = ["_routed_path"]
