"""The operation projection and its query, against a real Postgres.

The other side of the operation-summary contract. The run file beside this one
carries the shared reasoning about draining, replay and lag; what is here
is the operation's own: one event per stream, so one insert and no update, and
a name that is deliberately not unique.
"""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false

from datetime import UTC, datetime
from uuid import UUID, uuid4

import asyncpg
import pytest

from keeper.execution.adapters.postgres_operation_summary_lookup import (
    PostgresOperationSummaryLookup,
)
from keeper.execution.aggregates.operation.state import OperationName
from keeper.execution.projections.operation_summary import OperationSummaryProjection
from keeper.infrastructure.adapters.postgres_event_store import PostgresEventStore
from keeper.infrastructure.projection.worker import advance_subscriber_once
from tests._port_contracts._writers import EventStoreOperationWriter
from tests._port_contracts.operation_summary_lookup import CHECKS, Check

pytestmark = [pytest.mark.integration]


class _DrainingOperationWriter:
    """Append operation events, then let the projection catch up."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool
        self._writer = EventStoreOperationWriter(PostgresEventStore(pool))
        self._projection = OperationSummaryProjection()

    async def define(self, *, operation_id: UUID, name: OperationName, at: datetime) -> None:
        await self._writer.define(operation_id=operation_id, name=name, at=at)
        while await advance_subscriber_once(self._pool, self._projection):
            pass


@pytest.fixture
def lookup(db_pool: asyncpg.Pool) -> PostgresOperationSummaryLookup:
    return PostgresOperationSummaryLookup(db_pool)


@pytest.fixture
def writer(db_pool: asyncpg.Pool) -> _DrainingOperationWriter:
    return _DrainingOperationWriter(db_pool)


@pytest.mark.parametrize("check", CHECKS, ids=lambda c: c.__name__)
async def test_the_postgres_plan_summary_lookup_keeps_the_port_contract(
    check: Check, lookup: PostgresOperationSummaryLookup, writer: _DrainingOperationWriter
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
            OperationSummaryProjection.name,
        )
    assert row is not None
    assert row["last_position"] == 0


async def test_the_two_projections_advance_independently_of_each_other(
    db_pool: asyncpg.Pool, lookup: PostgresOperationSummaryLookup
) -> None:
    """Each has its own bookmark and its own subscription, so operation events
    do not move the execution projection's cursor and an operation defined while
    the execution projection is wedged still lands."""
    writer = EventStoreOperationWriter(PostgresEventStore(db_pool))
    await writer.define(operation_id=uuid4(), name=OperationName("count"), at=datetime.now(tz=UTC))

    assert await advance_subscriber_once(db_pool, OperationSummaryProjection()) == 1

    async with db_pool.acquire() as conn:
        execution_bookmark = await conn.fetchval(
            "SELECT last_position FROM projection_bookmarks WHERE name = $1",
            "proj_execution_execution_summary",
        )
    assert execution_bookmark == 0
    assert len((await lookup.list_operations(name=None, limit=10, cursor=None)).items) == 1


async def test_replaying_a_batch_leaves_the_table_exactly_as_it_was(
    db_pool: asyncpg.Pool, lookup: PostgresOperationSummaryLookup
) -> None:
    """Delivery is at-least-once, and the insert's ON CONFLICT is the only
    thing standing between a replay and a duplicate-key failure that would
    wedge the projection for good."""
    writer = _DrainingOperationWriter(db_pool)
    await writer.define(operation_id=uuid4(), name=OperationName("count"), at=datetime.now(tz=UTC))
    first = await lookup.list_operations(name=None, limit=10, cursor=None)

    async with db_pool.acquire() as conn:
        await conn.execute(
            "UPDATE projection_bookmarks SET last_transaction_id = '0'::xid8, "
            "last_position = 0 WHERE name = $1",
            OperationSummaryProjection.name,
        )
    while await advance_subscriber_once(db_pool, OperationSummaryProjection()):
        pass

    assert await lookup.list_operations(name=None, limit=10, cursor=None) == first
