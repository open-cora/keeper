"""The proposal projection and its query, against a real Postgres.

The other side of the proposal-summary contract. The files beside this
one carry the shared reasoning about draining, replay and lag; what is
here is this projection's own, and what it has that none of the others
do is a second event that rewrites two columns.

That is the hazard worth its own tests. An update arm on a replayed batch
has to leave the table where the first pass left it, and unlike an
insert it has no `ON CONFLICT` doing the work: it is idempotent only
because it writes values derived entirely from the event rather than
from what the row currently holds. Nothing in the source states that,
so it is checked here.
"""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import asyncpg
import pytest

from keeper.counsel.adapters.postgres_proposal_summary_lookup import (
    PostgresProposalSummaryLookup,
)
from keeper.counsel.aggregates.proposal import PROPOSAL_STREAM_TYPE, ProposalTaken
from keeper.counsel.aggregates.proposal import to_payload as proposal_payload
from keeper.counsel.projections.proposal_summary import ProposalSummaryProjection
from keeper.infrastructure.adapters.postgres_event_store import PostgresEventStore
from keeper.infrastructure.projection.worker import advance_subscriber_once
from keeper.infrastructure.slices.envelope import to_new_event
from tests._port_contracts._writers import EventStoreProposalWriter
from tests._port_contracts.proposal_summary_lookup import CHECKS, Check

pytestmark = [pytest.mark.integration]

_WHEN = datetime(2026, 3, 1, 9, 0, tzinfo=UTC)


class _DrainingProposalWriter:
    """Append proposal events, then let the projection catch up."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool
        self._writer = EventStoreProposalWriter(PostgresEventStore(pool))
        self._projection = ProposalSummaryProjection()

    async def make(
        self,
        *,
        proposal_id: UUID,
        actor_id: UUID,
        plan_id: UUID,
        at: datetime,
    ) -> None:
        await self._writer.make(proposal_id=proposal_id, actor_id=actor_id, plan_id=plan_id, at=at)
        await self._drain()

    async def take(
        self, *, proposal_id: UUID, execution_id: UUID, step_id: UUID, at: datetime
    ) -> None:
        await self._writer.take(
            proposal_id=proposal_id, execution_id=execution_id, step_id=step_id, at=at
        )
        await self._drain()

    async def _drain(self) -> None:
        while await advance_subscriber_once(self._pool, self._projection):
            pass


@pytest.fixture
def lookup(db_pool: asyncpg.Pool) -> PostgresProposalSummaryLookup:
    return PostgresProposalSummaryLookup(db_pool)


@pytest.fixture
def writer(db_pool: asyncpg.Pool) -> _DrainingProposalWriter:
    return _DrainingProposalWriter(db_pool)


@pytest.mark.parametrize("check", CHECKS, ids=lambda c: c.__name__)
async def test_the_postgres_proposal_summary_lookup_keeps_the_port_contract(
    check: Check, lookup: PostgresProposalSummaryLookup, writer: _DrainingProposalWriter
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
            ProposalSummaryProjection.name,
        )
    assert row is not None
    assert row["last_position"] == 0


async def test_a_proposal_event_does_not_move_another_contexts_bookmark(
    db_pool: asyncpg.Pool, lookup: PostgresProposalSummaryLookup
) -> None:
    """Six projections now tail one log across five contexts. Each has
    its own bookmark and its own subscription, so a proposal landing does
    not advance Execution's cursors past events they have not seen."""
    await EventStoreProposalWriter(PostgresEventStore(db_pool)).make(
        proposal_id=uuid4(), actor_id=uuid4(), plan_id=uuid4(), at=_WHEN
    )

    assert await advance_subscriber_once(db_pool, ProposalSummaryProjection()) == 1

    async with db_pool.acquire() as conn:
        execution_bookmark = await conn.fetchval(
            "SELECT last_position FROM projection_bookmarks WHERE name = $1",
            "proj_execution_execution_summary",
        )
    assert execution_bookmark == 0
    assert len((await lookup.list_proposals(is_open=None, limit=10, cursor=None)).items) == 1


async def test_replaying_a_batch_of_both_events_leaves_the_table_as_it_was(
    db_pool: asyncpg.Pool, lookup: PostgresProposalSummaryLookup
) -> None:
    """Delivery is at-least-once, and this projection replays an UPDATE as
    well as an INSERT. The insert has `ON CONFLICT`; the update has only
    the fact that it writes the event's own values rather than reading the
    row first, which is what makes a second pass a no-op."""
    writer = _DrainingProposalWriter(db_pool)
    proposal_id = uuid4()
    await writer.make(proposal_id=proposal_id, actor_id=uuid4(), plan_id=uuid4(), at=_WHEN)
    await writer.take(
        proposal_id=proposal_id,
        execution_id=uuid4(),
        step_id=uuid4(),
        at=_WHEN + timedelta(minutes=5),
    )
    first = await lookup.list_proposals(is_open=None, limit=10, cursor=None)

    async with db_pool.acquire() as conn:
        await conn.execute(
            "UPDATE projection_bookmarks SET last_transaction_id = '0'::xid8, "
            "last_position = 0 WHERE name = $1",
            ProposalSummaryProjection.name,
        )
    while await advance_subscriber_once(db_pool, ProposalSummaryProjection()):
        pass

    assert await lookup.list_proposals(is_open=None, limit=10, cursor=None) == first


async def test_a_take_arriving_before_its_genesis_does_not_wedge_the_projection(
    db_pool: asyncpg.Pool, lookup: PostgresProposalSummaryLookup
) -> None:
    """The ordering guarantee says this cannot happen, so the arm logs
    rather than raises. What is pinned here is that choice: a raise would
    roll the batch back forever and stop every later proposal appearing,
    which is a worse failure than one row missing.

    The event is appended by hand at version 0, because the writer's
    `take` appends at version 1 and so cannot produce the orphan this is
    about.
    """
    orphan = uuid4()
    taken = ProposalTaken(
        proposal_id=orphan, execution_id=uuid4(), step_id=uuid4(), occurred_at=_WHEN
    )
    await PostgresEventStore(db_pool).append(
        PROPOSAL_STREAM_TYPE,
        orphan,
        0,
        [
            to_new_event(
                event_type="ProposalTaken",
                payload=proposal_payload(taken),
                occurred_at=_WHEN,
                event_id=uuid4(),
                command_name="TakeProposal",
                correlation_id=uuid4(),
                principal_id=uuid4(),
            )
        ],
    )
    later = uuid4()
    await EventStoreProposalWriter(PostgresEventStore(db_pool)).make(
        proposal_id=later, actor_id=uuid4(), plan_id=uuid4(), at=_WHEN
    )

    while await advance_subscriber_once(db_pool, ProposalSummaryProjection()):
        pass

    page = await lookup.list_proposals(is_open=None, limit=10, cursor=None)
    found = {summary.proposal_id for summary in page.items}
    assert later in found, "the projection carried on past the orphan"
    assert orphan not in found, "an update with no row writes nothing"
