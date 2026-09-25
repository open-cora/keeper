"""The plan projection and its query, against a real Postgres.

The other side of the plan-summary contract. The run file beside this one
carries the shared reasoning about draining, replay and lag; what is here
is the plan's own: one event per stream, so one insert and no update, and
a name that is deliberately not unique.
"""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false

from datetime import UTC, datetime
from uuid import UUID, uuid4

import asyncpg
import pytest

from keeper.execution.adapters.postgres_plan_summary_lookup import PostgresPlanSummaryLookup
from keeper.execution.aggregates.plan.state import PlanName
from keeper.execution.projections.plan_summary import PlanSummaryProjection
from keeper.infrastructure.adapters.postgres_event_store import PostgresEventStore
from keeper.infrastructure.projection.worker import advance_subscriber_once
from tests._port_contracts._writers import EventStorePlanWriter
from tests._port_contracts.plan_summary_lookup import CHECKS, Check

pytestmark = [pytest.mark.integration]


class _DrainingPlanWriter:
    """Append plan events, then let the projection catch up."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool
        self._writer = EventStorePlanWriter(PostgresEventStore(pool))
        self._projection = PlanSummaryProjection()

    async def define(self, *, plan_id: UUID, name: PlanName, at: datetime) -> None:
        await self._writer.define(plan_id=plan_id, name=name, at=at)
        while await advance_subscriber_once(self._pool, self._projection):
            pass


@pytest.fixture
def lookup(db_pool: asyncpg.Pool) -> PostgresPlanSummaryLookup:
    return PostgresPlanSummaryLookup(db_pool)


@pytest.fixture
def writer(db_pool: asyncpg.Pool) -> _DrainingPlanWriter:
    return _DrainingPlanWriter(db_pool)


@pytest.mark.parametrize("check", CHECKS, ids=lambda c: c.__name__)
async def test_the_postgres_plan_summary_lookup_keeps_the_port_contract(
    check: Check, lookup: PostgresPlanSummaryLookup, writer: _DrainingPlanWriter
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
            PlanSummaryProjection.name,
        )
    assert row is not None
    assert row["last_position"] == 0


async def test_the_two_projections_advance_independently_of_each_other(
    db_pool: asyncpg.Pool, lookup: PostgresPlanSummaryLookup
) -> None:
    """Each has its own bookmark and its own subscription, so plan events
    do not move the execution projection's cursor and a plan defined while
    the execution projection is wedged still lands."""
    writer = EventStorePlanWriter(PostgresEventStore(db_pool))
    await writer.define(plan_id=uuid4(), name=PlanName("count"), at=datetime.now(tz=UTC))

    assert await advance_subscriber_once(db_pool, PlanSummaryProjection()) == 1

    async with db_pool.acquire() as conn:
        execution_bookmark = await conn.fetchval(
            "SELECT last_position FROM projection_bookmarks WHERE name = $1",
            "proj_execution_execution_summary",
        )
    assert execution_bookmark == 0
    assert len((await lookup.list_plans(name=None, limit=10, cursor=None)).items) == 1


async def test_replaying_a_batch_leaves_the_table_exactly_as_it_was(
    db_pool: asyncpg.Pool, lookup: PostgresPlanSummaryLookup
) -> None:
    """Delivery is at-least-once, and the insert's ON CONFLICT is the only
    thing standing between a replay and a duplicate-key failure that would
    wedge the projection for good."""
    writer = _DrainingPlanWriter(db_pool)
    await writer.define(plan_id=uuid4(), name=PlanName("count"), at=datetime.now(tz=UTC))
    first = await lookup.list_plans(name=None, limit=10, cursor=None)

    async with db_pool.acquire() as conn:
        await conn.execute(
            "UPDATE projection_bookmarks SET last_transaction_id = '0'::xid8, "
            "last_position = 0 WHERE name = $1",
            PlanSummaryProjection.name,
        )
    while await advance_subscriber_once(db_pool, PlanSummaryProjection()):
        pass

    assert await lookup.list_plans(name=None, limit=10, cursor=None) == first
