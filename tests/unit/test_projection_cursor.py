"""The pagination cursor is an opaque token clients hand back verbatim.

Two properties make it safe to expose. It round-trips exactly, so a client
paging forward lands where it left off rather than a microsecond away; and a
malformed one raises rather than decoding to something plausible, because a
silently-wrong cursor skips rows instead of erroring.
"""

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from hypothesis import given
from hypothesis import strategies as st

from keeper.infrastructure.projection.cursor import (
    InvalidCursorError,
    decode_cursor,
    encode_cursor,
)

pytestmark = pytest.mark.unit


def test_cursor_round_trips_the_exact_timestamp_and_id() -> None:
    at = datetime(2026, 9, 16, 12, 30, 45, 123456, tzinfo=UTC)
    item_id = uuid4()
    assert decode_cursor(encode_cursor(created_at=at, item_id=item_id)) == (at, item_id)


@given(
    at=st.datetimes(timezones=st.just(UTC)),
    item_id=st.uuids(),
)
def test_cursor_round_trips_for_any_timestamp_and_id(at: datetime, item_id: UUID) -> None:
    assert decode_cursor(encode_cursor(created_at=at, item_id=item_id)) == (at, item_id)


def test_cursor_is_url_safe_so_it_survives_a_query_string() -> None:
    cursor = encode_cursor(created_at=datetime.now(UTC), item_id=uuid4())
    assert "+" not in cursor
    assert "/" not in cursor
    assert "=" not in cursor


@pytest.mark.parametrize(
    "bad",
    ["", "not-base64!!", "YWJj", "Zm9vfGJhcg", "MjAyNi0wMS0wMVQwMDowMDowMA"],
    ids=["empty", "not-base64", "base64-but-no-separator", "bad-halves", "missing-uuid"],
)
def test_a_malformed_cursor_raises_rather_than_decoding_to_something_plausible(
    bad: str,
) -> None:
    with pytest.raises(InvalidCursorError):
        decode_cursor(bad)
