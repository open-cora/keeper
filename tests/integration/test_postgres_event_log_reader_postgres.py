"""The log reader, against a real Postgres.

The in-memory twin carries every contract test for this port, and it
cannot carry the two things that only a database has. Both are the
reasons the cursor is a pair rather than a position, so a reader that
passed in memory and failed here would fail by skipping events, silently,
in the one direction nobody notices.

  - `pg_snapshot_xmin` excludes an event whose transaction has not
    committed, so a reader never steps over a row it will not come back
    for. In memory there is no such row.
  - `(transaction_id, position)` orders events inside one transaction and
    across transactions that committed out of sequence. A bigserial alone
    does not, which is the bug this pair exists to prevent.

The SQL itself is the third thing, and the plainest: `$1::xid8`, the
`stream_type = ANY($3)` filter and the `transaction_id::text` alias are
text until a database parses them.
"""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false

import asyncio
from uuid import uuid4

import asyncpg
import pytest

from keeper.infrastructure.adapters.postgres_event_log_reader import PostgresEventLogReader
from keeper.infrastructure.adapters.postgres_event_store import PostgresEventStore
from keeper.infrastructure.ports.event_log_reader import LogCursor
from keeper.infrastructure.ports.event_store import StreamAppend
from tests._port_contracts.event_store import an_event

pytestmark = [pytest.mark.integration]

_EVERY_TYPE = ("Thing", "Other")


@pytest.fixture
def store(db_pool: asyncpg.Pool) -> PostgresEventStore:
    return PostgresEventStore(db_pool)


@pytest.fixture
def reader(db_pool: asyncpg.Pool) -> PostgresEventLogReader:
    return PostgresEventLogReader(db_pool)


async def test_an_appended_event_is_readable_from_the_beginning(
    store: PostgresEventStore, reader: PostgresEventLogReader
) -> None:
    await store.append("Thing", uuid4(), 0, [an_event("ThingRegistered")])

    page = await reader.read_after(LogCursor.BEGINNING, limit=10, stream_types=_EVERY_TYPE)

    assert [event.event_type for event in page.items] == ["ThingRegistered"]
    assert page.next_cursor is not None
    assert page.next_cursor.transaction_id > 0


async def test_resuming_from_the_cursor_returns_only_what_followed(
    store: PostgresEventStore, reader: PostgresEventLogReader
) -> None:
    await store.append("Thing", uuid4(), 0, [an_event("First")])
    first = await reader.read_after(LogCursor.BEGINNING, limit=10, stream_types=_EVERY_TYPE)
    assert first.next_cursor is not None

    await store.append("Thing", uuid4(), 0, [an_event("Second")])
    resumed = await reader.read_after(first.next_cursor, limit=10, stream_types=_EVERY_TYPE)

    assert [event.event_type for event in resumed.items] == ["Second"]


async def test_a_cursor_at_the_head_returns_an_empty_page_and_no_cursor(
    store: PostgresEventStore, reader: PostgresEventLogReader
) -> None:
    await store.append("Thing", uuid4(), 0, [an_event()])
    page = await reader.read_after(LogCursor.BEGINNING, limit=10, stream_types=_EVERY_TYPE)
    assert page.next_cursor is not None

    again = await reader.read_after(page.next_cursor, limit=10, stream_types=_EVERY_TYPE)

    assert not again.items
    assert again.next_cursor is None


async def test_the_filter_withholds_a_stream_type_it_was_not_given(
    store: PostgresEventStore, reader: PostgresEventLogReader
) -> None:
    await store.append("Thing", uuid4(), 0, [an_event("OnThing")])
    await store.append("Other", uuid4(), 0, [an_event("OnOther")])

    page = await reader.read_after(LogCursor.BEGINNING, limit=10, stream_types=("Thing",))

    assert [event.event_type for event in page.items] == ["OnThing"]


async def test_an_empty_filter_returns_nothing_rather_than_everything(
    store: PostgresEventStore, reader: PostgresEventLogReader
) -> None:
    await store.append("Thing", uuid4(), 0, [an_event()])

    page = await reader.read_after(LogCursor.BEGINNING, limit=10, stream_types=())

    assert not page.items


async def test_events_from_one_transaction_keep_their_order(
    store: PostgresEventStore, reader: PostgresEventLogReader
) -> None:
    """One xid8 spanning several positions is what the pair cursor is for."""
    await store.append("Thing", uuid4(), 0, [an_event("One"), an_event("Two"), an_event("Three")])

    page = await reader.read_after(LogCursor.BEGINNING, limit=10, stream_types=_EVERY_TYPE)

    assert [event.event_type for event in page.items] == ["One", "Two", "Three"]
    assert len({event.transaction_id for event in page.items}) == 1


async def test_paging_within_one_transaction_resumes_mid_stream(
    store: PostgresEventStore, reader: PostgresEventLogReader
) -> None:
    """A limit landing inside a transaction must not skip its remainder,
    which a cursor holding only the transaction id would do."""
    await store.append("Thing", uuid4(), 0, [an_event("One"), an_event("Two"), an_event("Three")])

    first = await reader.read_after(LogCursor.BEGINNING, limit=2, stream_types=_EVERY_TYPE)
    assert first.next_cursor is not None
    rest = await reader.read_after(first.next_cursor, limit=10, stream_types=_EVERY_TYPE)

    assert [event.event_type for event in first.items] == ["One", "Two"]
    assert [event.event_type for event in rest.items] == ["Three"]


async def test_an_uncommitted_event_is_not_readable(
    db_pool: asyncpg.Pool, store: PostgresEventStore, reader: PostgresEventLogReader
) -> None:
    """The in-flight exclusion, which is the whole reason for the xid8 half.

    A reader that returned this row would advance its cursor past a
    transaction that may still roll back, and would never come back for
    the rows that landed beside it.
    """
    started = asyncio.Event()
    release = asyncio.Event()

    async def hold_open() -> None:
        async with db_pool.acquire() as conn, conn.transaction():
            await store.append_streams(
                [
                    StreamAppend(
                        stream_type="Thing",
                        stream_id=uuid4(),
                        expected_version=0,
                        events=[an_event("Uncommitted")],
                    )
                ],
                conn=conn,
            )
            started.set()
            await release.wait()

    holder = asyncio.create_task(hold_open())
    await started.wait()
    try:
        page = await reader.read_after(LogCursor.BEGINNING, limit=10, stream_types=_EVERY_TYPE)
        assert [event.event_type for event in page.items] == []
    finally:
        release.set()
        await holder

    after = await reader.read_after(LogCursor.BEGINNING, limit=10, stream_types=_EVERY_TYPE)
    assert [event.event_type for event in after.items] == ["Uncommitted"]
