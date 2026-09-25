"""The size cap's boundary, and the scopes it must not touch.

The cap is the outermost middleware, so it sees every request including the
ones it has no business rejecting. Two things are easy to get wrong and
invisible once wrong: whether the limit is inclusive, and whether a non-HTTP
scope (a lifespan message, a websocket handshake) is passed through untouched.
A middleware that swallows a lifespan message breaks startup, not a request.
"""

from typing import Any

import pytest

from keeper.api.middleware import BodySizeLimitMiddleware

pytestmark = pytest.mark.unit


async def _send_body(*, content_length: int, limit: int, scope_type: str = "http") -> list[Any]:
    sent: list[Any] = []
    reached = False

    async def _app(_scope: Any, _receive: Any, _send: Any) -> None:
        nonlocal reached
        reached = True

    async def _receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b""}

    async def _send(message: dict[str, Any]) -> None:
        sent.append(message)

    middleware = BodySizeLimitMiddleware(_app, max_bytes=limit)
    scope = {
        "type": scope_type,
        "path": "/x",
        "method": "POST",
        "headers": [(b"content-length", str(content_length).encode())],
    }
    await middleware(scope, _receive, _send)
    return [reached, sent]


async def test_a_body_exactly_at_the_limit_is_allowed_through() -> None:
    reached, sent = await _send_body(content_length=100, limit=100)
    assert reached is True
    assert sent == []


async def test_a_body_one_byte_over_the_limit_is_rejected() -> None:
    reached, sent = await _send_body(content_length=101, limit=100)
    assert reached is False
    assert sent[0]["status"] == 413


async def test_a_non_http_scope_passes_through_without_inspection() -> None:
    """A lifespan or websocket scope carries no Content-Length contract. The
    middleware must forward it untouched rather than reason about it."""
    reached, sent = await _send_body(content_length=10_000, limit=100, scope_type="lifespan")
    assert reached is True
    assert sent == []


async def test_a_malformed_content_length_is_left_to_the_framework() -> None:
    sent: list[Any] = []
    reached = False

    async def _app(_scope: Any, _receive: Any, _send: Any) -> None:
        nonlocal reached
        reached = True

    async def _receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b""}

    async def _send(message: dict[str, Any]) -> None:
        sent.append(message)

    middleware = BodySizeLimitMiddleware(_app, max_bytes=100)
    scope = {
        "type": "http",
        "path": "/x",
        "method": "POST",
        "headers": [(b"content-length", b"not-a-number")],
    }
    await middleware(scope, _receive, _send)
    assert reached is True, "Starlette returns 400 for this; the cap must not pre-empt it"
