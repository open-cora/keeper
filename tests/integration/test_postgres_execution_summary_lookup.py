"""The projection and its query, against a real Postgres.

The other side of the execution-summary contract, and the only place the whole
read path runs: events into the log, the worker's advance loop over them,
rows into `proj_execution_execution_summary`, and the query reading them back.

The writer here appends and then drains, so every check in the shared
contract is really asserting "once the projection has caught up". That is
the one thing the in-memory driver cannot say, because a fold has nothing
to catch up to, and it is the reason the lag questions below are here
rather than in the contract.

The replay question matters more for this table than for its siblings.
Every other projection writes absolute values, so a replayed batch is
harmless by construction. This one tracks progress, which a counter
cannot do idempotently, and the test below is what keeps the set-union
that replaces it honest.
"""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import asyncpg
import pytest

from keeper.execution.adapters.postgres_execution_summary_lookup import (
    PostgresExecutionSummaryLookup,
)
from keeper.execution.projections.execution_summary import ExecutionSummaryProjection
from keeper.infrastructure.adapters.postgres_event_store import PostgresEventStore
from keeper.infrastructure.projection.worker import advance_subscriber_once
from tests._port_contracts._writers import EventStoreExecutionWriter
from tests._port_contracts.execution_summary_lookup import CHECKS, Check

pytestmark = [pytest.mark.integration]

_STEPS = ["move 2bmb:m1 to 0.0", "acquire tomo_scan", "move 2bmb:m2 to 5.0"]


class _DrainingExecutionWriter:
    """Append execution events, then let the projection catch up.

    The contract's checks read immediately after writing, which is
    exactly the race a projection has. Draining here rather than inside
    each check keeps the contract about what the adapters answer and
    leaves when they answer it to this tier.
    """

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool
        self._writer = EventStoreExecutionWriter(PostgresEventStore(pool))
        self._projection = ExecutionSummaryProjection()

    async def dispatch(
        self,
        *,
        execution_id: UUID,
        procedure_id: UUID,
        steps: list[str],
        at: datetime,
        beamline: str = "2-bm",
    ) -> None:
        await self._writer.dispatch(
            execution_id=execution_id,
            procedure_id=procedure_id,
            steps=steps,
            at=at,
            beamline=beamline,
        )
        await self._drain()

    async def claim(self, *, execution_id: UUID, at: datetime) -> None:
        await self._writer.claim(execution_id=execution_id, at=at)
        await self._drain()

    async def step(self, *, execution_id: UUID, index: int, at: datetime) -> None:
        await self._writer.step(execution_id=execution_id, index=index, at=at)
        await self._drain()

    async def end(self, *, execution_id: UUID, at: datetime) -> None:
        await self._writer.end(execution_id=execution_id, at=at)
        await self._drain()

    async def _drain(self) -> None:
        while await advance_subscriber_once(self._pool, self._projection):
            pass


@pytest.fixture
def lookup(db_pool: asyncpg.Pool) -> PostgresExecutionSummaryLookup:
    return PostgresExecutionSummaryLookup(db_pool)


@pytest.fixture
def writer(db_pool: asyncpg.Pool) -> _DrainingExecutionWriter:
    return _DrainingExecutionWriter(db_pool)


@pytest.mark.parametrize("check", CHECKS, ids=lambda c: c.__name__)
async def test_the_postgres_walk_summary_lookup_keeps_the_port_contract(
    check: Check, lookup: PostgresExecutionSummaryLookup, writer: _DrainingExecutionWriter
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
            ExecutionSummaryProjection.name,
        )
    assert row is not None
    assert row["last_position"] == 0


async def test_a_walk_is_invisible_until_the_projection_has_caught_up(
    db_pool: asyncpg.Pool, lookup: PostgresExecutionSummaryLookup
) -> None:
    """The one behaviour that only exists on this side of the port, and
    the one thing a caller has to know: a write returns before the read
    model shows it."""
    writer = EventStoreExecutionWriter(PostgresEventStore(db_pool))
    await writer.dispatch(
        execution_id=uuid4(),
        procedure_id=uuid4(),
        steps=list(_STEPS),
        at=datetime.now(tz=UTC),
    )

    before = await lookup.list_executions(
        procedure_id=None, beamline=None, status=None, limit=10, cursor=None
    )
    assert before.items == []

    await advance_subscriber_once(db_pool, ExecutionSummaryProjection())

    after = await lookup.list_executions(
        procedure_id=None, beamline=None, status=None, limit=10, cursor=None
    )
    assert len(after.items) == 1


async def test_replaying_a_batch_does_not_advance_the_progress_twice(
    db_pool: asyncpg.Pool, lookup: PostgresExecutionSummaryLookup
) -> None:
    """The reason this table holds a set and not a counter. Delivery is
    at-least-once, so a crash between applying a batch and committing the
    bookmark replays it, and an increment would report an execution further
    along than it is. Rewinding the bookmark by hand is the only way to
    make that happen on demand."""
    writer = _DrainingExecutionWriter(db_pool)
    execution_id = uuid4()
    started = datetime.now(tz=UTC)
    await writer.dispatch(
        execution_id=execution_id,
        procedure_id=uuid4(),
        steps=list(_STEPS),
        at=started,
    )
    await writer.step(execution_id=execution_id, index=0, at=started + timedelta(minutes=1))
    await writer.step(execution_id=execution_id, index=1, at=started + timedelta(minutes=2))
    first = await lookup.list_executions(
        procedure_id=None, beamline=None, status=None, limit=10, cursor=None
    )
    assert first.items[0].reported_count == 2

    async with db_pool.acquire() as conn:
        await conn.execute(
            "UPDATE projection_bookmarks SET last_transaction_id = '0'::xid8, "
            "last_position = 0 WHERE name = $1",
            ExecutionSummaryProjection.name,
        )
    while await advance_subscriber_once(db_pool, ExecutionSummaryProjection()):
        pass

    assert (
        await lookup.list_executions(
            procedure_id=None, beamline=None, status=None, limit=10, cursor=None
        )
        == first
    )


async def test_a_step_for_a_walk_the_table_never_saw_does_not_wedge_the_worker(
    db_pool: asyncpg.Pool, lookup: PostgresExecutionSummaryLookup
) -> None:
    """A step with no row ahead of it cannot happen through the ordering,
    and if it ever did, stopping the whole read model over one execution would
    be the wrong answer. Narrowing the subscription to steps only is how a
    projection that missed a genesis is simulated."""
    execution_id = uuid4()
    writer = EventStoreExecutionWriter(PostgresEventStore(db_pool))
    at = datetime.now(tz=UTC)
    await writer.dispatch(
        execution_id=execution_id,
        procedure_id=uuid4(),
        steps=list(_STEPS),
        at=at,
    )
    await writer.step(execution_id=execution_id, index=0, at=at)

    steps_only = ExecutionSummaryProjection()
    steps_only.subscribed_event_types = frozenset({"ExecutionStepDone"})

    assert await advance_subscriber_once(db_pool, steps_only) == 1

    page = await lookup.list_executions(
        procedure_id=None, beamline=None, status=None, limit=10, cursor=None
    )
    assert page.items == []
