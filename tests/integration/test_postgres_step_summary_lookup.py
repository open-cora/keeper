"""The gap projection and its query, against a real Postgres.

The other side of the step-summary contract, and the only place the
whole read path runs: execution events and dataset events into one log,
the worker's advance loop over them, rows into
`proj_execution_step_summary`, and the query reading back the rows with
a reference and no dataset.

This is the only projection in the tree fed by two bounded contexts, so
it is the only one whose drain has to cover two streams of events that
nothing orders against each other. The writer below drains after every
append for that reason: a check that filed a dataset and then read
would otherwise be racing the arm that fills the column.
"""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false

from datetime import UTC, datetime
from uuid import UUID, uuid4

import asyncpg
import pytest

from keeper.execution.adapters.postgres_step_summary_lookup import PostgresStepSummaryLookup
from keeper.execution.projections.step_summary import StepSummaryProjection
from keeper.infrastructure.adapters.postgres_event_store import PostgresEventStore
from keeper.infrastructure.projection.worker import advance_subscriber_once
from keeper.shared.identifier import Identifier
from tests._port_contracts._writers import EventStoreDatasetWriter, EventStoreExecutionWriter
from tests._port_contracts.step_summary_lookup import CHECKS, Check

pytestmark = [pytest.mark.integration]


class _DrainingStepWriter:
    """Append across both contexts, then let the projection catch up.

    The contract's checks read immediately after writing, which is
    exactly the race a projection has. Draining here rather than inside
    each check keeps the contract about what the adapters answer and
    leaves when they answer it to this tier.
    """

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool
        event_store = PostgresEventStore(pool)
        self._executions = EventStoreExecutionWriter(event_store)
        self._datasets = EventStoreDatasetWriter(event_store)
        self._projection = StepSummaryProjection()

    async def dispatch(
        self,
        *,
        execution_id: UUID,
        procedure_id: UUID,
        steps: list[str],
        at: datetime,
        beamline: str = "2-bm",
        step_ids: list[UUID] | None = None,
    ) -> None:
        await self._executions.dispatch(
            execution_id=execution_id,
            procedure_id=procedure_id,
            steps=steps,
            at=at,
            beamline=beamline,
            step_ids=step_ids,
        )
        await self._drain()

    async def step(
        self,
        *,
        execution_id: UUID,
        index: int,
        at: datetime,
        engine_reference: str | None = None,
    ) -> None:
        await self._executions.step(
            execution_id=execution_id, index=index, at=at, engine_reference=engine_reference
        )
        await self._drain()

    async def register(
        self,
        *,
        dataset_id: UUID,
        execution_id: UUID,
        step_id: UUID,
        external_ref: Identifier,
        at: datetime,
    ) -> None:
        await self._datasets.register(
            dataset_id=dataset_id,
            execution_id=execution_id,
            step_id=step_id,
            external_ref=external_ref,
            at=at,
        )
        await self._drain()

    async def _drain(self) -> None:
        while await advance_subscriber_once(self._pool, self._projection):
            pass


@pytest.fixture
def lookup(db_pool: asyncpg.Pool) -> PostgresStepSummaryLookup:
    return PostgresStepSummaryLookup(db_pool)


@pytest.fixture
def writer(db_pool: asyncpg.Pool) -> _DrainingStepWriter:
    return _DrainingStepWriter(db_pool)


@pytest.mark.parametrize("check", CHECKS, ids=lambda c: c.__name__)
async def test_the_postgres_step_summary_lookup_keeps_the_port_contract(
    check: Check, lookup: PostgresStepSummaryLookup, writer: _DrainingStepWriter
) -> None:
    await check(lookup, writer)


async def test_the_migration_seeded_the_bookmark_this_projection_reads(
    db_pool: asyncpg.Pool,
) -> None:
    """Without the row the worker raises on its first advance, forever,
    inside its own backoff loop. Nothing else in the suite would say so:
    the checks above create it implicitly by succeeding."""
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT last_position FROM projection_bookmarks WHERE name = $1",
            StepSummaryProjection.name,
        )
    assert row is not None
    assert row["last_position"] == 0


async def test_a_dataset_that_arrives_before_the_step_report_still_fills_the_row(
    db_pool: asyncpg.Pool, lookup: PostgresStepSummaryLookup, writer: _DrainingStepWriter
) -> None:
    """The two arms are fed by two streams and nothing orders them.

    Nothing stops a dataset being registered for a step before that
    step's own ending is projected: the write side does not require the
    step to have ended, and the two streams advance independently. An
    arm that assumed the report had landed would leave the row looking
    like a gap forever, which is the wrong answer in the direction
    nobody checks.
    """
    execution_id, step_ids = uuid4(), [uuid4()]
    at = datetime(2026, 3, 1, 9, 0, tzinfo=UTC)

    await writer.dispatch(
        execution_id=execution_id,
        procedure_id=uuid4(),
        steps=["run tomo_scan"],
        at=at,
        step_ids=step_ids,
    )
    await writer.register(
        dataset_id=uuid4(),
        execution_id=execution_id,
        step_id=step_ids[0],
        external_ref=Identifier(scheme="posix-file", value="/data/early.h5"),
        at=at,
    )
    await writer.step(execution_id=execution_id, index=0, at=at, engine_reference="/data/early.h5")

    page = await lookup.list_steps_without_datasets(beamline=None, limit=10, cursor=None)

    assert page.items == []


async def test_replaying_the_whole_log_leaves_the_table_where_it_was(
    db_pool: asyncpg.Pool, lookup: PostgresStepSummaryLookup, writer: _DrainingStepWriter
) -> None:
    """Delivery is at-least-once, so every arm has to be safe to redo.

    The bookmark is reset and the log replayed from the start. A
    genesis insert that conflicted, or an update that accumulated
    rather than overwrote, shows up here as a different answer the
    second time.
    """
    execution_id, step_ids = uuid4(), [uuid4(), uuid4()]
    at = datetime(2026, 3, 1, 9, 0, tzinfo=UTC)

    await writer.dispatch(
        execution_id=execution_id,
        procedure_id=uuid4(),
        steps=["set 2bmb:m1 to 0.0", "run tomo_scan"],
        at=at,
        step_ids=step_ids,
    )
    await writer.step(execution_id=execution_id, index=0, at=at)
    await writer.step(
        execution_id=execution_id, index=1, at=at, engine_reference="/data/replayed.h5"
    )

    before = await lookup.list_steps_without_datasets(beamline=None, limit=10, cursor=None)

    async with db_pool.acquire() as conn:
        await conn.execute(
            "UPDATE projection_bookmarks "
            "SET last_position = 0, last_transaction_id = '0'::xid8 WHERE name = $1",
            StepSummaryProjection.name,
        )
    while await advance_subscriber_once(db_pool, StepSummaryProjection()):
        pass

    after = await lookup.list_steps_without_datasets(beamline=None, limit=10, cursor=None)

    assert [item.step_id for item in before.items] == step_ids[1:]
    assert [item.step_id for item in after.items] == [item.step_id for item in before.items]
