"""The advance loop, against a real Postgres.

This is the machinery every read model in this codebase will stand on, and
its guarantees are the kind that cannot be asserted against a fake: the batch
is one transaction, the ordering key is `(transaction_id, position)` rather
than `position` alone, and the bookmark is what makes a restart resume rather
than replay.

No bounded context registers a projection. Each folds its aggregates from
the stream on every read and says why in its own `read.py`, so the loop has
never had a domain subscriber to run. The subscriber here is a counter that
records what it was handed, which is enough: every property below is a
property of the loop, not of any domain.
"""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import asyncpg
import pytest

from keeper.infrastructure.projection.bookmark import (
    MissingBookmarkError,
    ensure_bookmarks,
    read_bookmark,
)
from keeper.infrastructure.projection.worker import advance_subscriber_once

pytestmark = [pytest.mark.integration]

_APPEND = """
INSERT INTO events (
    event_id, stream_type, stream_id, version, event_type,
    payload, correlation_id, occurred_at
) VALUES ($1, 'thing', $2, $3, $4, '{}'::jsonb, $5, $6)
"""


_SCRATCH_TABLE = """
CREATE TABLE IF NOT EXISTS proj_scratch (
    event_id UUID PRIMARY KEY,
    event_type TEXT NOT NULL
)
"""


class _Recorder:
    """A Subscriber that writes a row per event, and can be told to fail.

    It writes to Postgres rather than only to a Python list on purpose. A
    subscriber that touches no database has nothing to roll back, so a test
    built on one would assert the batch-transaction property while exercising
    none of it. That version of this class let a mutation removing
    `conn.transaction()` pass every test here.
    """

    def __init__(self, name: str, *event_types: str, fail_on: str | None = None) -> None:
        self.name = name
        self.subscribed_event_types = frozenset(event_types)
        self.fail_on = fail_on
        self.seen: list[str] = []

    async def apply(self, event: Any, conn: Any) -> None:
        if self.fail_on is not None and event.event_type == self.fail_on:
            msg = f"subscriber refused {event.event_type}"
            raise RuntimeError(msg)
        await conn.execute(
            "INSERT INTO proj_scratch (event_id, event_type) VALUES ($1, $2)",
            event.event_id,
            event.event_type,
        )
        self.seen.append(event.event_type)


@pytest.fixture(autouse=True)
async def _scratch(db_pool: asyncpg.Pool) -> None:
    async with db_pool.acquire() as conn:
        await conn.execute(_SCRATCH_TABLE)


async def _scratch_rows(pool: asyncpg.Pool) -> list[str]:
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT event_type FROM proj_scratch")
    return [r["event_type"] for r in rows]


async def _append(pool: asyncpg.Pool, event_type: str, *, version: int, stream: UUID) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            _APPEND, uuid4(), stream, version, event_type, uuid4(), datetime.now(UTC)
        )


async def _register(pool: asyncpg.Pool, name: str) -> None:
    await ensure_bookmarks(pool, frozenset({name}), reactions_at_head=False)


async def test_advance_delivers_appended_events_and_reports_how_many(
    db_pool: asyncpg.Pool,
) -> None:
    stream = uuid4()
    await _register(db_pool, "recorder")
    for i, name in enumerate(["ThingRegistered", "ThingRenamed"], start=1):
        await _append(db_pool, name, version=i, stream=stream)

    subscriber = _Recorder("recorder", "ThingRegistered", "ThingRenamed")
    assert await advance_subscriber_once(db_pool, subscriber) == 2
    assert subscriber.seen == ["ThingRegistered", "ThingRenamed"]


async def test_advance_returns_zero_when_the_bookmark_is_already_at_the_head(
    db_pool: asyncpg.Pool,
) -> None:
    await _register(db_pool, "recorder")
    await _append(db_pool, "ThingRegistered", version=1, stream=uuid4())
    subscriber = _Recorder("recorder", "ThingRegistered")
    await advance_subscriber_once(db_pool, subscriber)

    assert await advance_subscriber_once(db_pool, subscriber) == 0


async def test_a_second_advance_resumes_after_the_bookmark_rather_than_replaying(
    db_pool: asyncpg.Pool,
) -> None:
    """The bookmark is the only thing standing between a restart and a replay.

    A projection that replays is merely slow. A reaction that replays re-does
    side effects, so this is the property the whole subsystem exists for.
    """
    stream = uuid4()
    await _register(db_pool, "recorder")
    await _append(db_pool, "ThingRegistered", version=1, stream=stream)
    subscriber = _Recorder("recorder", "ThingRegistered", "ThingRenamed")
    await advance_subscriber_once(db_pool, subscriber)

    await _append(db_pool, "ThingRenamed", version=2, stream=stream)
    assert await advance_subscriber_once(db_pool, subscriber) == 1
    assert subscriber.seen == ["ThingRegistered", "ThingRenamed"], "no event seen twice"


async def test_advance_delivers_only_the_event_types_the_subscriber_asked_for(
    db_pool: asyncpg.Pool,
) -> None:
    stream = uuid4()
    await _register(db_pool, "recorder")
    for i, name in enumerate(["ThingRegistered", "ThingIgnored", "ThingRenamed"], start=1):
        await _append(db_pool, name, version=i, stream=stream)

    subscriber = _Recorder("recorder", "ThingRegistered", "ThingRenamed")
    await advance_subscriber_once(db_pool, subscriber)
    assert subscriber.seen == ["ThingRegistered", "ThingRenamed"]


async def test_advance_stops_at_the_batch_size(db_pool: asyncpg.Pool) -> None:
    stream = uuid4()
    await _register(db_pool, "recorder")
    for i in range(1, 6):
        await _append(db_pool, "ThingRegistered", version=i, stream=stream)

    subscriber = _Recorder("recorder", "ThingRegistered")
    assert await advance_subscriber_once(db_pool, subscriber, batch_size=2) == 2
    assert len(subscriber.seen) == 2


async def test_a_failing_subscriber_leaves_the_bookmark_where_it_was(
    db_pool: asyncpg.Pool,
) -> None:
    """At-least-once delivery: the batch is one transaction, so a subscriber
    that raises mid-batch rolls back the bookmark advance along with whatever
    it had already written. The alternative is silent event loss."""
    stream = uuid4()
    await _register(db_pool, "recorder")
    for i, name in enumerate(["ThingRegistered", "ThingBroken"], start=1):
        await _append(db_pool, name, version=i, stream=stream)

    async with db_pool.acquire() as conn:
        before = await read_bookmark(conn, "recorder")

    subscriber = _Recorder("recorder", "ThingRegistered", "ThingBroken", fail_on="ThingBroken")
    with pytest.raises(RuntimeError, match="refused"):
        await advance_subscriber_once(db_pool, subscriber)

    assert subscriber.seen == ["ThingRegistered"], "the first event was applied"
    assert await _scratch_rows(db_pool) == [], "and its write was rolled back with the batch"
    async with db_pool.acquire() as conn:
        assert await read_bookmark(conn, "recorder") == before


async def test_a_retry_after_a_failure_redelivers_the_whole_batch(
    db_pool: asyncpg.Pool,
) -> None:
    """The other half of at-least-once: nothing is dropped by the rollback."""
    stream = uuid4()
    await _register(db_pool, "recorder")
    for i, name in enumerate(["ThingRegistered", "ThingBroken"], start=1):
        await _append(db_pool, name, version=i, stream=stream)

    failing = _Recorder("recorder", "ThingRegistered", "ThingBroken", fail_on="ThingBroken")
    with pytest.raises(RuntimeError):
        await advance_subscriber_once(db_pool, failing)

    recovered = _Recorder("recorder", "ThingRegistered", "ThingBroken")
    assert await advance_subscriber_once(db_pool, recovered) == 2
    assert recovered.seen == ["ThingRegistered", "ThingBroken"]


async def test_advancing_a_subscriber_with_no_bookmark_row_refuses_loudly(
    db_pool: asyncpg.Pool,
) -> None:
    """Silently treating a missing bookmark as position zero would replay all
    history against a subscriber nobody registered."""
    subscriber = _Recorder("never_registered", "ThingRegistered")
    with pytest.raises(MissingBookmarkError):
        await advance_subscriber_once(db_pool, subscriber)


async def test_a_reaction_starts_at_the_head_so_enabling_it_replays_nothing(
    db_pool: asyncpg.Pool,
) -> None:
    """A projection folds history and must see all of it. A reaction acts on
    the world, so replaying history means re-performing it."""
    await _append(db_pool, "ThingRegistered", version=1, stream=uuid4())
    # No `reactions_at_head` kwarg: starting at the head is the DEFAULT, and
    # passing it explicitly would leave the default untested.
    await ensure_bookmarks(db_pool, frozenset({"reactor"}))

    subscriber = _Recorder("reactor", "ThingRegistered")
    assert await advance_subscriber_once(db_pool, subscriber) == 0
    assert subscriber.seen == []
