"""The pursuit projection and its query, against a real Postgres.

The other side of the pursuit-summary contract. The files beside this one
carry the shared reasoning about draining, replay and lag; what is here is
this projection's own, and what it has that none of the others do is a
status column.

That is the hazard worth its own tests. Every sibling derives its status
from nullable timestamps on both sides, so the two spellings stay close by
construction. This one stores the word, so the table and the fold could
drift, and the arms that write it have to be idempotent without reading
what is there: a replayed close writes the status its own outcome implies,
and a replayed round writes the count its own index implies, neither of
them touching the row first.
"""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import asyncpg
import pytest

from keeper.infrastructure.adapters.postgres_event_store import PostgresEventStore
from keeper.infrastructure.projection.worker import advance_subscriber_once
from keeper.infrastructure.slices.envelope import to_new_event
from keeper.pursuit.adapters.postgres_pursuit_summary_lookup import (
    PostgresPursuitSummaryLookup,
)
from keeper.pursuit.aggregates.pursuit import (
    PURSUIT_STREAM_TYPE,
    PursuitRoundClosed,
    PursuitStatus,
    RoundOutcome,
    to_payload,
)
from keeper.pursuit.projections.pursuit_summary import PursuitSummaryProjection
from tests._port_contracts._writers import EventStorePursuitWriter
from tests._port_contracts.pursuit_summary_lookup import CHECKS, Check

pytestmark = [pytest.mark.integration]

_WHEN = datetime(2026, 3, 1, 9, 0, tzinfo=UTC)


class _DrainingPursuitWriter:
    """Append pursuit events, then let the projection catch up."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool
        self._writer = EventStorePursuitWriter(PostgresEventStore(pool))
        self._projection = PursuitSummaryProjection()

    async def start(
        self, *, pursuit_id: UUID, actor_id: UUID, goal: str, beamline: str, at: datetime
    ) -> None:
        await self._writer.start(
            pursuit_id=pursuit_id, actor_id=actor_id, goal=goal, beamline=beamline, at=at
        )
        await self._drain()

    async def open_round(self, *, pursuit_id: UUID, round_index: int, at: datetime) -> None:
        await self._writer.open_round(pursuit_id=pursuit_id, round_index=round_index, at=at)
        await self._drain()

    async def close_round(
        self, *, pursuit_id: UUID, round_index: int, outcome: RoundOutcome, at: datetime
    ) -> None:
        await self._writer.close_round(
            pursuit_id=pursuit_id, round_index=round_index, outcome=outcome, at=at
        )
        await self._drain()

    async def resume(self, *, pursuit_id: UUID, at: datetime) -> None:
        await self._writer.resume(pursuit_id=pursuit_id, at=at)
        await self._drain()

    async def withdraw(self, *, pursuit_id: UUID, at: datetime) -> None:
        await self._writer.withdraw(pursuit_id=pursuit_id, at=at)
        await self._drain()

    async def _drain(self) -> None:
        while await advance_subscriber_once(self._pool, self._projection):
            pass


@pytest.fixture
def lookup(db_pool: asyncpg.Pool) -> PostgresPursuitSummaryLookup:
    return PostgresPursuitSummaryLookup(db_pool)


@pytest.fixture
def writer(db_pool: asyncpg.Pool) -> _DrainingPursuitWriter:
    return _DrainingPursuitWriter(db_pool)


@pytest.mark.parametrize("check", CHECKS, ids=lambda c: c.__name__)
async def test_the_postgres_pursuit_summary_lookup_keeps_the_port_contract(
    check: Check, lookup: PostgresPursuitSummaryLookup, writer: _DrainingPursuitWriter
) -> None:
    await check(lookup, writer)


async def test_the_migration_seeded_the_bookmark_this_projection_reads(
    db_pool: asyncpg.Pool,
) -> None:
    """Without the row the worker raises on its first advance, forever,
    inside its own backoff loop."""
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT last_position FROM projection_bookmarks WHERE name = $1",
            PursuitSummaryProjection.name,
        )
    assert row is not None
    assert row["last_position"] == 0


async def test_a_pursuit_event_does_not_move_another_contexts_bookmark(
    db_pool: asyncpg.Pool, lookup: PostgresPursuitSummaryLookup
) -> None:
    """Seven projections now tail one log across six contexts. Each has its
    own bookmark and its own subscription, so a pursuit landing does not
    advance Counsel's cursors past events they have not seen."""
    await EventStorePursuitWriter(PostgresEventStore(db_pool)).start(
        pursuit_id=uuid4(), actor_id=uuid4(), goal="find the edge", beamline="2-bm", at=_WHEN
    )

    assert await advance_subscriber_once(db_pool, PursuitSummaryProjection()) == 1

    async with db_pool.acquire() as conn:
        inquiry_bookmark = await conn.fetchval(
            "SELECT last_position FROM projection_bookmarks WHERE name = $1",
            "proj_counsel_inquiry_summary",
        )
    assert inquiry_bookmark == 0
    page = await lookup.list_pursuits(status=None, beamline=None, limit=10, cursor=None)
    assert len(page.items) == 1


async def test_replaying_the_whole_history_leaves_the_table_as_it_was(
    db_pool: asyncpg.Pool, lookup: PostgresPursuitSummaryLookup
) -> None:
    """Delivery is at-least-once, and this projection replays four updates
    as well as an insert. None of them has `ON CONFLICT` doing the work:
    each is idempotent only because it writes values derived entirely from
    the event rather than from what the row currently holds.

    The whole sequence is replayed rather than one arm, because the status
    is the column that could drift, and it is written by three different
    arms in an order a second pass has to reproduce.
    """
    writer = _DrainingPursuitWriter(db_pool)
    pursuit_id = uuid4()
    await writer.start(
        pursuit_id=pursuit_id, actor_id=uuid4(), goal="find the edge", beamline="2-bm", at=_WHEN
    )
    await writer.open_round(pursuit_id=pursuit_id, round_index=0, at=_WHEN)
    await writer.close_round(
        pursuit_id=pursuit_id,
        round_index=0,
        outcome=RoundOutcome.REFERRED,
        at=_WHEN + timedelta(minutes=1),
    )
    await writer.resume(pursuit_id=pursuit_id, at=_WHEN + timedelta(minutes=2))
    await writer.open_round(pursuit_id=pursuit_id, round_index=1, at=_WHEN)
    first = await lookup.list_pursuits(status=None, beamline=None, limit=10, cursor=None)

    async with db_pool.acquire() as conn:
        await conn.execute(
            "UPDATE projection_bookmarks SET last_transaction_id = '0'::xid8, "
            "last_position = 0 WHERE name = $1",
            PursuitSummaryProjection.name,
        )
    while await advance_subscriber_once(db_pool, PursuitSummaryProjection()):
        pass

    assert await lookup.list_pursuits(status=None, beamline=None, limit=10, cursor=None) == first
    assert first.items[0].status is PursuitStatus.RUNNING
    assert first.items[0].round_count == 2


async def test_a_close_arriving_before_its_genesis_does_not_wedge_the_projection(
    db_pool: asyncpg.Pool, lookup: PostgresPursuitSummaryLookup
) -> None:
    """The ordering guarantee says this cannot happen, so the arm logs
    rather than raises. What is pinned here is that choice: a raise would
    roll the batch back forever and stop every later pursuit appearing,
    which is a worse failure than one row missing.

    The event is appended by hand at version 0, because the writer's
    `close_round` counts what it has written and so cannot produce the
    orphan this is about.
    """
    orphan = uuid4()
    await PostgresEventStore(db_pool).append(
        PURSUIT_STREAM_TYPE,
        orphan,
        0,
        [
            to_new_event(
                event_type="PursuitRoundClosed",
                payload=to_payload(
                    PursuitRoundClosed(
                        pursuit_id=orphan,
                        round_index=0,
                        outcome=RoundOutcome.STALLED.value,
                        proposal_id=None,
                        dispatched_id=None,
                        occurred_at=_WHEN,
                    )
                ),
                occurred_at=_WHEN,
                event_id=uuid4(),
                command_name="ClosePursuitRound",
                correlation_id=uuid4(),
                principal_id=uuid4(),
            )
        ],
    )
    later = uuid4()
    await EventStorePursuitWriter(PostgresEventStore(db_pool)).start(
        pursuit_id=later, actor_id=uuid4(), goal="find the edge", beamline="2-bm", at=_WHEN
    )

    while await advance_subscriber_once(db_pool, PursuitSummaryProjection()):
        pass

    page = await lookup.list_pursuits(status=None, beamline=None, limit=10, cursor=None)
    found = {summary.pursuit_id for summary in page.items}
    assert later in found, "the projection carried on past the orphan"
    assert orphan not in found, "an update with no row writes nothing"
