"""The Execution slices, driven end to end against a real Postgres.

Every other test of this context runs on `InMemoryEventStore`, which
hands back the very objects it was given. The parameters schema is the
reason that is not good enough here. In state it is a Python dict; in a
row it is a JSONB document that went out through a serialiser and came
back through a codec. A plan that folds correctly from a dict it never
serialised proves nothing about the one the deployed system reads back,
and the schema is the field a caller validates its own requests against.

The queries below spell `"Plan"` as a literal rather than using
`PLAN_STREAM_TYPE`. That is the only independent side these tests have:
a query built from the writer's own constant agrees with the writer
however wrong the constant is.

The handlers come from `wire_execution`, not from `bind`, so these go
through the same composition the application boots: tracing and the
idempotency wrapper.
"""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false

import asyncio
import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import asyncpg
import pytest

from keeper.execution import wire_execution
from keeper.execution.aggregates.execution import (
    EngineReport,
    EngineState,
    ExecutionAlreadyEndedError,
    ExecutionCannotBeClaimedError,
    ExecutionNotFoundError,
    ExecutionStatus,
    StepOutcome,
    StepRunCannotBeReportedError,
    load_execution,
)
from keeper.execution.aggregates.plan import PlanName, PlanNotFoundError, load_plan
from keeper.execution.aggregates.procedure import (
    AcquireStep,
    MoveStep,
    load_procedure,
    runs_plan,
)
from keeper.execution.features.claim_execution import ClaimExecution
from keeper.execution.features.define_plan import DefinePlan
from keeper.execution.features.define_procedure import DefineProcedure
from keeper.execution.features.dispatch_execution import DispatchExecution
from keeper.execution.features.end_execution import EndExecution
from keeper.execution.features.get_execution import GetExecution
from keeper.execution.features.get_plan import GetPlan
from keeper.execution.features.get_procedure import GetProcedure
from keeper.execution.features.report_step import ReportExecutionStep
from keeper.execution.features.report_step_run import ReportStepRun
from keeper.execution.wire import ExecutionHandlers
from keeper.infrastructure.adapters.postgres_event_store import PostgresEventStore
from keeper.infrastructure.deps import make_postgres_kernel
from keeper.infrastructure.ports import ConcurrencyError
from keeper.infrastructure.ports.authorize import AllowAllAuthorize
from keeper.infrastructure.ports.clock import SystemClock
from keeper.infrastructure.ports.id_generator import UUIDv7Generator
from keeper.infrastructure.settings import Settings

pytestmark = [pytest.mark.integration]

_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "exposure_seconds": {"type": "number", "minimum": 0},
        "detector": {"type": "string", "enum": ["pilatus", "eiger"]},
    },
    "required": ["exposure_seconds", "detector"],
}
"""Nested and multi-keyword on purpose.

A flat one-property schema would survive almost any serialisation
mistake. This one has an object inside an object and a list inside that,
which is where a codec that flattened, reordered or stringified
something would show up.
"""


@pytest.fixture
def handlers(db_pool: asyncpg.Pool) -> ExecutionHandlers:
    """The Execution bundle, wired exactly as the application wires it."""
    return wire_execution(
        make_postgres_kernel(
            db_pool,
            settings=Settings(app_env="test"),
            clock=SystemClock(),
            id_generator=UUIDv7Generator(),
            authz=AllowAllAuthorize(),
        )
    )


async def _a_procedure(handlers: ExecutionHandlers) -> UUID:
    """A plan and a procedure acquiring with it, through the wired handlers.

    Two steps, a move then an acquisition, so a test naming a step by
    index or by position is naming one of two rather than the only one.
    """
    plan_id = await handlers.define_plan(
        DefinePlan(name="count", parameters_schema=_SCHEMA),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )
    return await handlers.define_procedure(
        DefineProcedure(
            name="align_then_scan",
            beamline="2-bm",
            steps=(
                MoveStep(record="2bmb:m1", to=0.0),
                AcquireStep(
                    plan_id=plan_id,
                    parameters={"exposure_seconds": 0.25, "detector": "eiger"},
                    scopes=("2bmb:det:",),
                ),
            ),
        ),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )


async def _a_dispatched_execution(handlers: ExecutionHandlers) -> UUID:
    """One dispatch of that procedure. Returns the execution id."""
    return await handlers.dispatch_execution(
        DispatchExecution(procedure_id=await _a_procedure(handlers)),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )


async def test_a_plan_survives_a_round_trip_through_jsonb(
    handlers: ExecutionHandlers, db_pool: asyncpg.Pool
) -> None:
    """Fold what Postgres gives back, not what was handed to the store."""
    plan_id = await handlers.define_plan(
        DefinePlan(name="grid_scan", parameters_schema=_SCHEMA),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )

    store = PostgresEventStore(db_pool)
    plan = await load_plan(store, plan_id)

    assert plan is not None
    assert plan.id == plan_id
    assert plan.name == PlanName("grid_scan")
    assert plan.parameters_schema == _SCHEMA


async def test_the_stored_row_holds_the_schema_under_the_pinned_stream_type(
    handlers: ExecutionHandlers, db_pool: asyncpg.Pool
) -> None:
    """Read the raw JSONB, so the shape is asserted and not just the fold.

    A fold that agrees with itself would pass even if the schema were
    stored as a string, or with its keys renamed. The stored shape is a
    contract with every future reader of this table, so it is checked
    directly rather than through the reader that wrote it.
    """
    plan_id = await handlers.define_plan(
        DefinePlan(name="grid_scan", parameters_schema=_SCHEMA),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )

    # `payload::text` rather than `payload`: the pool registers a JSONB
    # codec, so the plain column comes back already decoded. Reading the
    # text is reading what the column holds.
    row = await db_pool.fetchrow(
        "SELECT event_type, payload::text AS payload FROM events "
        "WHERE stream_type = $1 AND stream_id = $2",
        "Plan",
        plan_id,
    )

    assert row is not None
    assert row["event_type"] == "PlanDefined"
    payload = json.loads(row["payload"])
    assert payload["plan_name"] == "grid_scan"
    assert payload["parameters_schema"] == _SCHEMA
    assert "name" not in payload, "the bare key is what the personal-data rule refuses"


async def test_the_read_slice_answers_from_a_real_stream(
    handlers: ExecutionHandlers,
) -> None:
    """Both slices through one pool, which is how the application runs them."""
    plan_id = await handlers.define_plan(
        DefinePlan(name="count", parameters_schema=_SCHEMA),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )

    plan = await handlers.get_plan(
        GetPlan(plan_id=plan_id), principal_id=uuid4(), correlation_id=uuid4()
    )

    assert plan.id == plan_id
    assert plan.name == PlanName("count")


async def test_reading_a_plan_that_was_never_defined_is_refused(
    handlers: ExecutionHandlers,
) -> None:
    with pytest.raises(PlanNotFoundError):
        await handlers.get_plan(
            GetPlan(plan_id=uuid4()), principal_id=uuid4(), correlation_id=uuid4()
        )


async def _the_acquisition(handlers: ExecutionHandlers, execution_id: UUID) -> UUID:
    """The id of the one step of that execution that runs a plan.

    Two reads, because the execution does not say which of its steps is
    an acquisition. It says which composed step each one came from, and
    the procedure is what says which of those runs a plan. That is the
    join every outside caller makes, so it is worth making here rather
    than reaching past it.
    """
    execution = await handlers.get_execution(
        GetExecution(execution_id=execution_id), principal_id=uuid4(), correlation_id=uuid4()
    )
    procedure = await handlers.get_procedure(
        GetProcedure(procedure_id=execution.procedure_id),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )
    acquisitions = {
        composed.id for composed in procedure.steps if runs_plan(composed.step) is not None
    }
    return next(step.id for step in execution.steps if step.procedure_step_id in acquisitions)


async def test_a_procedure_survives_a_round_trip_with_its_typed_steps(
    handlers: ExecutionHandlers, db_pool: asyncpg.Pool
) -> None:
    """The second JSONB carrier in this context, and the harder one.

    A plan's schema is a document this system stores and never reads
    back into types. A procedure's steps are a discriminated union: they
    go out as dictionaries and have to come back as `MoveStep` and
    `AcquireStep` with their floats still floats and their ids still
    ids. A fold from objects it never serialised proves none of that.

    The cross-aggregate read is the other part real SQL adds. The
    decider checks each acquisition's parameters against a schema that
    came back out of JSONB.
    """
    procedure_id = await _a_procedure(handlers)

    store = PostgresEventStore(db_pool)
    procedure = await load_procedure(store, procedure_id)

    assert procedure is not None
    move, acquire = procedure.steps
    assert move.step == MoveStep(record="2bmb:m1", to=0.0)
    assert isinstance(acquire.step, AcquireStep)
    assert acquire.step.parameters == {"exposure_seconds": 0.25, "detector": "eiger"}
    assert acquire.step.scopes == ("2bmb:det:",)
    assert move.id != acquire.id


async def test_an_execution_copies_the_steps_its_procedure_holds(
    handlers: ExecutionHandlers, db_pool: asyncpg.Pool
) -> None:
    """The copy has to survive a round trip too, and it is a different shape.

    A procedure keeps its steps as a union; an execution keeps a
    rendered sentence, an id of its own, and the id of the composed step
    it came from. Both go through JSONB and neither can be checked from
    the other.
    """
    execution_id = await _a_dispatched_execution(handlers)

    store = PostgresEventStore(db_pool)
    execution = await load_execution(store, execution_id)
    procedure = await load_procedure(store, execution.procedure_id) if execution else None

    assert execution is not None
    assert procedure is not None
    assert execution.steps[0].describes == "move 2bmb:m1 to 0.0"
    assert [step.procedure_step_id for step in execution.steps] == [
        composed.id for composed in procedure.steps
    ]


async def test_the_three_aggregates_are_filed_under_different_stream_types(
    handlers: ExecutionHandlers, db_pool: asyncpg.Pool
) -> None:
    """Read the raw rows, so the routing key is asserted and not assumed.

    Three aggregates live in one context and one table, and the only
    thing keeping their histories apart is the `stream_type` column.
    Two aggregates writing under one value would fold each other's rows,
    and every fold-based test would still pass on a store that hands
    back only what it was asked for.
    """
    execution_id = await _a_dispatched_execution(handlers)

    rows = await db_pool.fetch(
        "SELECT stream_type, event_type FROM events ORDER BY position",
    )

    assert [(r["stream_type"], r["event_type"]) for r in rows] == [
        ("Plan", "PlanDefined"),
        ("Procedure", "ProcedureDefined"),
        ("Execution", "ExecutionDispatched"),
    ]
    assert execution_id


async def test_composing_against_a_plan_that_does_not_exist_is_refused(
    handlers: ExecutionHandlers,
) -> None:
    with pytest.raises(PlanNotFoundError):
        await handlers.define_procedure(
            DefineProcedure(
                name="one_scan",
                beamline="2-bm",
                steps=(AcquireStep(plan_id=uuid4(), parameters={}, scopes=("2bmb:det:",)),),
            ),
            principal_id=uuid4(),
            correlation_id=uuid4(),
        )


async def test_reading_an_execution_that_was_never_dispatched_is_refused(
    handlers: ExecutionHandlers,
) -> None:
    with pytest.raises(ExecutionNotFoundError):
        await handlers.get_execution(
            GetExecution(execution_id=uuid4()), principal_id=uuid4(), correlation_id=uuid4()
        )


async def test_two_concurrent_endings_leave_one_winner(
    handlers: ExecutionHandlers, db_pool: asyncpg.Pool
) -> None:
    """The UNIQUE constraint decides, not a Python lock.

    Both callers fold the same live execution and both try to append at the
    same version. In memory a lock serialises them and the loser meets
    the decider's refusal instead; here the second INSERT violates
    events_stream_version_unique and the adapter turns that into
    ConcurrencyError. Either way exactly one ending lands, which is the
    invariant, and only real SQL exercises the mechanism that enforces it
    in production.
    """
    execution_id = await _a_dispatched_execution(handlers)

    results = await asyncio.gather(
        handlers.end_execution(
            EndExecution(execution_id=execution_id), principal_id=uuid4(), correlation_id=uuid4()
        ),
        handlers.end_execution(
            EndExecution(execution_id=execution_id), principal_id=uuid4(), correlation_id=uuid4()
        ),
        return_exceptions=True,
    )

    failures = [r for r in results if isinstance(r, BaseException)]
    assert len(failures) == 1, f"expected exactly one loser, got {results}"
    assert isinstance(failures[0], ConcurrencyError | ExecutionAlreadyEndedError)

    endings = await db_pool.fetchval(
        "SELECT count(*) FROM events WHERE stream_id = $1 AND event_type = 'ExecutionEnded'",
        execution_id,
    )
    assert endings == 1


async def test_an_ending_survives_the_round_trip_and_shows_on_the_read_slice(
    handlers: ExecutionHandlers,
) -> None:
    """The status is derived, so it has to survive a reload to mean anything.

    The unit tests fold events they built in memory. Here the ending goes
    to Postgres, comes back through the codec, and the fold recomputes
    the status from the event type on the row. A status that was written
    onto a payload would pass both; one that is derived only passes if
    the row's type came back intact.
    """
    execution_id = await _a_dispatched_execution(handlers)

    await handlers.end_execution(
        EndExecution(execution_id=execution_id), principal_id=uuid4(), correlation_id=uuid4()
    )
    execution = await handlers.get_execution(
        GetExecution(execution_id=execution_id), principal_id=uuid4(), correlation_id=uuid4()
    )

    assert execution.status is ExecutionStatus.ENDED


async def test_an_engine_pause_cycle_survives_the_round_trip_and_reads_back_as_running(
    handlers: ExecutionHandlers, db_pool: asyncpg.Pool
) -> None:
    """A state the stream returns to, recovered from rows rather than memory.

    The ending round trip above starts and finishes on different
    statuses, so a fold that stopped reading after the second row would
    still get it right. This one starts and finishes on the same one,
    which is what makes the row count the load-bearing assertion: the
    engine state alone cannot tell a completed cycle from two appends
    that never happened.

    It also exercises the one field on a step that is found by id rather
    than by index, which only survives a reload if the ids on the
    genesis payload came back as the same ids.
    """
    execution_id = await _a_dispatched_execution(handlers)
    step_id = await _the_acquisition(handlers, execution_id)

    for reported in (EngineReport.STARTED, EngineReport.PAUSED, EngineReport.RESUMED):
        await handlers.report_step_run(
            ReportStepRun(execution_id=execution_id, step_id=step_id, reported=reported),
            principal_id=uuid4(),
            correlation_id=uuid4(),
        )

    store = PostgresEventStore(db_pool)
    execution = await load_execution(store, execution_id)
    assert execution is not None
    assert execution.steps[1].engine_state is EngineState.RUNNING

    written = await db_pool.fetch(
        "SELECT event_type FROM events WHERE stream_id = $1 ORDER BY version",
        execution_id,
    )
    assert [row["event_type"] for row in written] == [
        "ExecutionDispatched",
        "ExecutionStepEngineStarted",
        "ExecutionStepEnginePaused",
        "ExecutionStepEngineResumed",
    ]


async def test_two_concurrent_claims_leave_one_winner(
    handlers: ExecutionHandlers, db_pool: asyncpg.Pool
) -> None:
    """The same race as the endings, on the transient this context added.

    Worth running separately rather than trusting the endings case. Two
    drivers believing they own one traversal is the failure the
    Dispatched status exists to make visible, and it is the one race
    where the loser has already started moving hardware. Both callers
    fold a dispatched execution and both append at version one; the
    UNIQUE constraint is what makes the second a loser rather than a
    second claim on a claimed execution.
    """
    execution_id = await _a_dispatched_execution(handlers)

    results = await asyncio.gather(
        handlers.claim_execution(
            ClaimExecution(execution_id=execution_id), principal_id=uuid4(), correlation_id=uuid4()
        ),
        handlers.claim_execution(
            ClaimExecution(execution_id=execution_id), principal_id=uuid4(), correlation_id=uuid4()
        ),
        return_exceptions=True,
    )

    failures = [r for r in results if isinstance(r, BaseException)]
    assert len(failures) == 1, f"expected exactly one loser, got {results}"
    assert isinstance(failures[0], ConcurrencyError | ExecutionCannotBeClaimedError)

    claims = await db_pool.fetchval(
        "SELECT count(*) FROM events WHERE stream_id = $1 AND event_type = 'ExecutionClaimed'",
        execution_id,
    )
    assert claims == 1


async def test_an_engine_report_that_does_not_follow_is_refused_across_a_reload(
    handlers: ExecutionHandlers,
) -> None:
    """The engine state machine reads its own previous answer off a row.

    The state it compares against is not stored as a column: it is
    rebuilt by folding the events back, so a report that does not follow
    is only refused if the previous report came back out of Postgres as
    the event type it went in as.
    """
    execution_id = await _a_dispatched_execution(handlers)
    step_id = await _the_acquisition(handlers, execution_id)

    await handlers.report_step_run(
        ReportStepRun(execution_id=execution_id, step_id=step_id, reported=EngineReport.STARTED),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )

    with pytest.raises(StepRunCannotBeReportedError):
        await handlers.report_step_run(
            ReportStepRun(
                execution_id=execution_id, step_id=step_id, reported=EngineReport.RESUMED
            ),
            principal_id=uuid4(),
            correlation_id=uuid4(),
        )


async def test_a_reported_time_is_stored_as_given_and_the_write_time_is_not(
    handlers: ExecutionHandlers, db_pool: asyncpg.Pool
) -> None:
    """The two timestamps, read off a real row, side by side.

    This is the only tier that can see the change at all. The read model
    exposes no times, so the unit and contract tiers can prove the field
    reaches the command and not that it reaches the column.

    Both halves matter. `occurred_at` must be exactly the instant the
    caller reported, years before this test runs, which says a backfill
    lands honestly. `recorded_at` must be near now and nowhere near the
    reported time, which says a caller cannot touch it: it comes from the
    table's own DEFAULT, never from this application. That split is the
    whole reason an unchecked instant is safe to accept.
    """
    reported = datetime(2019, 3, 4, 9, 30, tzinfo=UTC)
    execution_id = await _a_dispatched_execution(handlers)

    await handlers.claim_execution(
        ClaimExecution(execution_id=execution_id, occurred_at=reported),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )

    row = await db_pool.fetchrow(
        "SELECT occurred_at, recorded_at FROM events "
        "WHERE stream_id = $1 AND event_type = 'ExecutionClaimed'",
        execution_id,
    )

    assert row["occurred_at"] == reported
    assert row["recorded_at"] != reported
    assert (row["recorded_at"] - reported).days > 365, (
        "recorded_at must be the store's own write time, not the reported one"
    )


async def test_a_report_with_no_reported_time_is_stamped_by_the_clock(
    handlers: ExecutionHandlers, db_pool: asyncpg.Pool
) -> None:
    """The fallback, against real SQL, so the column is never left null.

    `occurred_at` is NOT NULL with no database default, so a handler that
    passed the command's `None` straight through would raise on insert
    rather than quietly storing nothing. Worth pinning here because the
    in-memory store would accept a null without complaint.
    """
    execution_id = await _a_dispatched_execution(handlers)

    await handlers.report_step(
        ReportExecutionStep(execution_id=execution_id, index=0, outcome=StepOutcome.DONE),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )

    stamps = await db_pool.fetch(
        "SELECT occurred_at FROM events WHERE stream_id = $1 ORDER BY version",
        execution_id,
    )
    assert all(row["occurred_at"] is not None for row in stamps)
    assert len(stamps) == 2


async def test_replaying_an_idempotency_key_writes_one_stream(
    handlers: ExecutionHandlers, db_pool: asyncpg.Pool
) -> None:
    """The wrapper is in the bundle, so the retry has to be checked through it.

    The unit tests call the bare handler, which has no wrapper at all,
    and the contract test checks the two ids match. Neither looks at the
    table. A wrapper that returned the cached id while still appending
    would pass both and leave a second plan behind.
    """
    command = DefinePlan(name="count", parameters_schema=_SCHEMA)
    caller = uuid4()

    first = await handlers.define_plan(
        command, principal_id=caller, correlation_id=uuid4(), idempotency_key="a-retried-request"
    )
    second = await handlers.define_plan(
        command, principal_id=caller, correlation_id=uuid4(), idempotency_key="a-retried-request"
    )

    assert first == second
    written = await db_pool.fetchval(
        "SELECT count(*) FROM events WHERE stream_type = $1 AND stream_id = $2", "Plan", first
    )
    assert written == 1
