"""The procedure projection and its query, against a real Postgres.

The other side of the procedure-summary contract. The run file carries
the shared reasoning about draining, replay and lag; what is here is the
procedure's own: one event per stream, so one insert and no update, a
name that is deliberately not unique, and a step count read whole off the
genesis rather than accumulated.
"""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false

from datetime import UTC, datetime
from uuid import UUID, uuid4

import asyncpg
import pytest

from keeper.execution.adapters.postgres_procedure_summary_lookup import (
    PostgresProcedureSummaryLookup,
)
from keeper.execution.aggregates.procedure.state import ProcedureName
from keeper.execution.projections.procedure_summary import ProcedureSummaryProjection
from keeper.infrastructure.adapters.postgres_event_store import PostgresEventStore
from keeper.infrastructure.projection.worker import advance_subscriber_once
from tests._port_contracts._writers import EventStoreProcedureWriter
from tests._port_contracts.procedure_summary_lookup import CHECKS, Check

pytestmark = [pytest.mark.integration]


class _DrainingProcedureWriter:
    """Append procedure events, then let the projection catch up."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool
        self._writer = EventStoreProcedureWriter(PostgresEventStore(pool))
        self._projection = ProcedureSummaryProjection()

    async def define(
        self,
        *,
        procedure_id: UUID,
        name: ProcedureName,
        steps: int,
        at: datetime,
        beamline: str = "2-bm",
    ) -> None:
        await self._writer.define(
            procedure_id=procedure_id, name=name, steps=steps, at=at, beamline=beamline
        )
        while await advance_subscriber_once(self._pool, self._projection):
            pass


@pytest.fixture
def lookup(db_pool: asyncpg.Pool) -> PostgresProcedureSummaryLookup:
    return PostgresProcedureSummaryLookup(db_pool)


@pytest.fixture
def writer(db_pool: asyncpg.Pool) -> _DrainingProcedureWriter:
    return _DrainingProcedureWriter(db_pool)


@pytest.mark.parametrize("check", CHECKS, ids=lambda c: c.__name__)
async def test_the_postgres_procedure_summary_lookup_keeps_the_port_contract(
    check: Check, lookup: PostgresProcedureSummaryLookup, writer: _DrainingProcedureWriter
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
            ProcedureSummaryProjection.name,
        )
    assert row is not None
    assert row["last_position"] == 0


async def test_replaying_a_batch_leaves_the_step_count_exactly_as_it_was(
    db_pool: asyncpg.Pool, lookup: PostgresProcedureSummaryLookup
) -> None:
    """The execution summary could not hold a counter because progress
    accumulates under at-least-once delivery. This count does not
    accumulate: it is read whole off one genesis payload, so a replayed
    batch writes the same number the first delivery did. Rewinding the
    bookmark by hand is what proves the difference is real rather than
    argued."""
    writer = _DrainingProcedureWriter(db_pool)
    await writer.define(
        procedure_id=uuid4(),
        name=ProcedureName("tomography"),
        steps=7,
        at=datetime.now(tz=UTC),
    )
    first = await lookup.list_procedures(name=None, limit=10, cursor=None)
    assert first.items[0].step_count == 7

    async with db_pool.acquire() as conn:
        await conn.execute(
            "UPDATE projection_bookmarks SET last_transaction_id = '0'::xid8, "
            "last_position = 0 WHERE name = $1",
            ProcedureSummaryProjection.name,
        )
    while await advance_subscriber_once(db_pool, ProcedureSummaryProjection()):
        pass

    assert await lookup.list_procedures(name=None, limit=10, cursor=None) == first
