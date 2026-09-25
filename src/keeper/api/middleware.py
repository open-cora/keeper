"""ASGI middlewares for the FastAPI app.

Currently:
  - BodySizeLimitMiddleware: rejects requests whose Content-Length
    header exceeds a configurable limit with HTTP 413 Payload Too Large.

Production deployments should ALSO enforce body size at the reverse
proxy (nginx `client_max_body_size`, Traefik `maxRequestBodyBytes`,
Cloudflare default ~100MB). The application middleware is defense in
depth for honest clients that respect Content-Length and provides
correct behaviour in dev/test where there is no proxy.

Known gap: requests using Transfer-Encoding: chunked WITHOUT a
Content-Length header are not rejected by this middleware (we'd need
to wrap `receive` and stream-count bytes). Those should be caught at
the proxy layer or via a streaming-body limit added later if needed.
"""

import json
from collections.abc import Awaitable, Callable
from typing import Any

from keeper.infrastructure.logging import get_logger

Scope = dict[str, Any]
Receive = Callable[[], Awaitable[dict[str, Any]]]
Send = Callable[[dict[str, Any]], Awaitable[None]]

# structlog loggers are lazy: get_logger() returns a proxy and config
# is applied at first .info() call. Module-level binding is safe even
# though configure_logging() runs later in build_kernel().
_log = get_logger(__name__)


class BodySizeLimitMiddleware:
    """Reject HTTP requests whose declared Content-Length exceeds `max_bytes`.

    Sends a 413 Payload Too Large with a JSON `{"detail": ...}` body,
    the same shape as the BC exception handlers, so clients see uniform
    error responses across all rejection sources.
    """

    def __init__(self, app: Any, *, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Headers in ASGI scope are a list of (bytes, bytes) tuples.
        # Build a dict for case-insensitive lookup. Header names are
        # lowercased per ASGI spec.
        headers = dict(scope.get("headers", []))
        raw_length = headers.get(b"content-length")
        if raw_length is not None:
            try:
                length = int(raw_length)
            except ValueError:
                # Malformed Content-Length is its own client error;
                # let downstream handle it (Starlette returns 400).
                length = 0
            if length > self.max_bytes:
                _log.info(
                    "body_size_limit.rejected",
                    path=scope.get("path"),
                    method=scope.get("method"),
                    content_length=length,
                    limit=self.max_bytes,
                )
                detail = f"Request body of {length} bytes exceeds limit of {self.max_bytes} bytes"
                body = json.dumps({"detail": detail}).encode()
                await send(
                    {
                        "type": "http.response.start",
                        "status": 413,
                        "headers": [
                            (b"content-type", b"application/json"),
                            (b"content-length", str(len(body)).encode()),
                        ],
                    }
                )
                await send({"type": "http.response.body", "body": body})
                return

        await self.app(scope, receive, send)
