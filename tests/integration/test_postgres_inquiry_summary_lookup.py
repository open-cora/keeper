"""The inquiry projection and its query, against a real Postgres.

The other side of the inquiry-summary contract. The files beside this one
carry the shared reasoning about draining, replay and lag; what is here is
this projection's own.

What it has that none of the others do is a record with three states and no
column holding which. The status is computed from two nullable timestamps on
the way out, so a row can be read wrong without any write being wrong, and
the contract suite is where that is pinned. What is left for this file is
the projection's own hazards: two update arms that have to survive a replay,
and a transition arriving with no row under it.
"""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import asyncpg
import pytest

from keeper.counsel.adapters.postgres_inquiry_summary_lookup import (
    PostgresInquirySummaryLookup,
)
from keeper.counsel.aggregates.inquiry import INQUIRY_STREAM_TYPE, InquiryClaimed
from keeper.counsel.aggregates.inquiry import to_payload as inquiry_payload
from keeper.counsel.projections.inquiry_summary import InquirySummaryProjection
from keeper.infrastructure.adapters.postgres_event_store import PostgresEventStore
from keeper.infrastructure.projection.worker import advance_subscriber_once
from keeper.infrastructure.slices.envelope import to_new_event
from tests._port_contracts._writers import EventStoreInquiryWriter
from tests._port_contracts.inquiry_summary_lookup import CHECKS, Check

pytestmark = [pytest.mark.integration]

_WHEN = datetime(2026, 3, 1, 9, 0, tzinfo=UTC)


class _DrainingInquiryWriter:
    """Append inquiry events, then let the projection catch up."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool
        self._writer = EventStoreInquiryWriter(PostgresEventStore(pool))
        self._projection = InquirySummaryProjection()

    async def make(
        self,
        *,
        inquiry_id: UUID,
        actor_id: UUID,
        execution_id: UUID,
        objective: str,
        execution_step_count: int,
        at: datetime,
    ) -> None:
        await self._writer.make(
            inquiry_id=inquiry_id,
            actor_id=actor_id,
            execution_id=execution_id,
            objective=objective,
            execution_step_count=execution_step_count,
            at=at,
        )
        await self._drain()

    async def claim(self, *, inquiry_id: UUID, at: datetime) -> None:
        await self._writer.claim(inquiry_id=inquiry_id, at=at)
        await self._drain()

    async def answer(
        self,
        *,
        inquiry_id: UUID,
        conclusion: str,
        observed_step_count: int,
        execution_ended: bool,
        proposal_id: UUID | None,
        at: datetime,
    ) -> None:
        await self._writer.answer(
            inquiry_id=inquiry_id,
            conclusion=conclusion,
            observed_step_count=observed_step_count,
            execution_ended=execution_ended,
            proposal_id=proposal_id,
            at=at,
        )
        await self._drain()

    async def _drain(self) -> None:
        while await advance_subscriber_once(self._pool, self._projection):
            pass


@pytest.fixture
def lookup(db_pool: asyncpg.Pool) -> PostgresInquirySummaryLookup:
    return PostgresInquirySummaryLookup(db_pool)


@pytest.fixture
def writer(db_pool: asyncpg.Pool) -> _DrainingInquiryWriter:
    return _DrainingInquiryWriter(db_pool)


@pytest.mark.parametrize("check", CHECKS, ids=lambda c: c.__name__)
async def test_the_postgres_inquiry_summary_lookup_keeps_the_port_contract(
    check: Check, lookup: PostgresInquirySummaryLookup, writer: _DrainingInquiryWriter
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
            InquirySummaryProjection.name,
        )
    assert row is not None
    assert row["last_position"] == 0


async def test_an_inquiry_event_does_not_move_another_projections_bookmark(
    db_pool: asyncpg.Pool, lookup: PostgresInquirySummaryLookup
) -> None:
    """Seven projections now tail one log, two of them in this context. Each
    has its own bookmark and its own subscription, so an inquiry landing does
    not advance the proposal summary past events it has not seen."""
    await EventStoreInquiryWriter(PostgresEventStore(db_pool)).make(
        inquiry_id=uuid4(),
        actor_id=uuid4(),
        execution_id=uuid4(),
        objective="find the edge",
        execution_step_count=6,
        at=_WHEN,
    )

    assert await advance_subscriber_once(db_pool, InquirySummaryProjection()) == 1

    async with db_pool.acquire() as conn:
        proposal_bookmark = await conn.fetchval(
            "SELECT last_position FROM projection_bookmarks WHERE name = $1",
            "proj_counsel_proposal_summary",
        )
    assert proposal_bookmark == 0
    assert len((await lookup.list_inquiries(status=None, limit=10, cursor=None)).items) == 1


async def test_replaying_a_batch_of_all_three_events_leaves_the_table_as_it_was(
    db_pool: asyncpg.Pool, lookup: PostgresInquirySummaryLookup
) -> None:
    """Delivery is at-least-once, and this projection replays two UPDATEs as
    well as an INSERT. The insert has `ON CONFLICT`; the updates have only
    the fact that they write the event's own values rather than reading the
    row first, which is what makes a second pass a no-op."""
    writer = _DrainingInquiryWriter(db_pool)
    inquiry_id = uuid4()
    await writer.make(
        inquiry_id=inquiry_id,
        actor_id=uuid4(),
        execution_id=uuid4(),
        objective="find the edge",
        execution_step_count=6,
        at=_WHEN,
    )
    await writer.claim(inquiry_id=inquiry_id, at=_WHEN + timedelta(minutes=2))
    await writer.answer(
        inquiry_id=inquiry_id,
        conclusion="Propose",
        observed_step_count=4,
        execution_ended=False,
        proposal_id=uuid4(),
        at=_WHEN + timedelta(minutes=5),
    )
    first = await lookup.list_inquiries(status=None, limit=10, cursor=None)

    async with db_pool.acquire() as conn:
        await conn.execute(
            "UPDATE projection_bookmarks SET last_transaction_id = '0'::xid8, "
            "last_position = 0 WHERE name = $1",
            InquirySummaryProjection.name,
        )
    while await advance_subscriber_once(db_pool, InquirySummaryProjection()):
        pass

    assert await lookup.list_inquiries(status=None, limit=10, cursor=None) == first


async def test_a_claim_arriving_before_its_genesis_does_not_wedge_the_projection(
    db_pool: asyncpg.Pool, lookup: PostgresInquirySummaryLookup
) -> None:
    """The ordering guarantee says this cannot happen, so the arm logs rather
    than raises. What is pinned here is that choice: a raise would roll the
    batch back forever and stop every later inquiry appearing, which is a
    worse failure than one row missing.

    The event is appended by hand at version 0, because the writer's `claim`
    appends after a genesis and so cannot produce the orphan this is about.
    """
    orphan = uuid4()
    claimed = InquiryClaimed(inquiry_id=orphan, occurred_at=_WHEN)
    await PostgresEventStore(db_pool).append(
        INQUIRY_STREAM_TYPE,
        orphan,
        0,
        [
            to_new_event(
                event_type="InquiryClaimed",
                payload=inquiry_payload(claimed),
                occurred_at=_WHEN,
                event_id=uuid4(),
                command_name="ClaimInquiry",
                correlation_id=uuid4(),
                principal_id=uuid4(),
            )
        ],
    )
    later = uuid4()
    await EventStoreInquiryWriter(PostgresEventStore(db_pool)).make(
        inquiry_id=later,
        actor_id=uuid4(),
        execution_id=uuid4(),
        objective="find the edge",
        execution_step_count=6,
        at=_WHEN,
    )

    while await advance_subscriber_once(db_pool, InquirySummaryProjection()):
        pass

    page = await lookup.list_inquiries(status=None, limit=10, cursor=None)
    found = {summary.inquiry_id for summary in page.items}
    assert later in found, "the projection carried on past the orphan"
    assert orphan not in found, "an update with no row writes nothing"
