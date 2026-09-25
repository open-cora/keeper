"""Opaque keyset-pagination cursor encode / decode.

The convention: every `proj_*` table includes a
`(created_at, id)` natural sort key, and every list endpoint paginates
via an opaque base64-encoded `(created_at, UUID)` cursor produced by
these helpers. Uniform format across BCs means a future "swap to
cursor-based pagination across all endpoints" never lands.

The cursor is base64url-encoded (URL-safe, no padding) so it fits
cleanly in a query string. The encoded body is `<isoformat>|<uuid>`;
both halves are deterministic (UUIDs canonicalize to one string form,
and we round-trip datetimes through `isoformat()` which preserves
timezone). Malformed cursors raise `InvalidCursorError`, which list
routes map to HTTP 422.
"""

import base64
from datetime import datetime
from uuid import UUID


class InvalidCursorError(Exception):
    """Cursor failed to decode (corrupt base64, missing separator,
    malformed timestamp / UUID). Routes map to HTTP 422."""

    def __init__(self, raw: str, reason: str) -> None:
        super().__init__(
            f"Invalid cursor {raw!r}: {reason}. Cursors must come "
            "from a previous response's next_cursor field."
        )
        self.raw = raw
        self.reason = reason


def encode_cursor(*, created_at: datetime, item_id: UUID) -> str:
    """Encode a (created_at, item_id) pair to an opaque cursor string.

    The encoded form is base64url(`<isoformat>|<uuid>`) with padding
    stripped. The `|` separator is safe because neither isoformat
    timestamps nor UUIDs contain it.
    """
    raw = f"{created_at.isoformat()}|{item_id}"
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def decode_cursor(cursor: str) -> tuple[datetime, UUID]:
    """Inverse of `encode_cursor`. Raises `InvalidCursorError` on any
    decoding failure."""
    try:
        padded = cursor + "=" * ((4 - len(cursor) % 4) % 4)
        raw_bytes = base64.urlsafe_b64decode(padded.encode())
        raw = raw_bytes.decode()
    except (ValueError, UnicodeDecodeError) as exc:
        raise InvalidCursorError(cursor, f"base64 decode failed: {exc}") from exc

    if "|" not in raw:
        raise InvalidCursorError(cursor, "missing '|' separator")
    ts_str, id_str = raw.split("|", 1)

    try:
        created_at = datetime.fromisoformat(ts_str)
    except ValueError as exc:
        raise InvalidCursorError(cursor, f"malformed timestamp {ts_str!r}: {exc}") from exc

    try:
        item_id = UUID(id_str)
    except ValueError as exc:
        raise InvalidCursorError(cursor, f"malformed UUID {id_str!r}: {exc}") from exc

    return created_at, item_id


__all__ = ["InvalidCursorError", "decode_cursor", "encode_cursor"]
