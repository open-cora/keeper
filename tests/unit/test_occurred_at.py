"""A caller saying when something it is reporting actually happened.

Three things, and they answer to different readers.

The normaliser is a pure function and is tested as one. The handlers are
tested as a table, because "every command that reports something honours
the reported time" is one behaviour with several instances, and a slice
that took the field and ignored it would pass every other test in the
suite. The idempotency case is here rather than next to the other retry
tests because the bug it guards against is created by this field and by
nothing else.

Which commands are in the table is itself the claim worth reading. Every
one of them records something that happened somewhere else: a driver
reporting a step, whatever watches an engine reporting its run, a claim,
an ending. The commands NOT here are the ones that record an act this
system performs, and they take no such field at all.
"""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

import pytest

from keeper.execution.aggregates.execution import (
    EXECUTION_STREAM_TYPE,
    EngineReport,
    StepOutcome,
    load_execution,
)
from keeper.execution.aggregates.procedure import AcquireStep
from keeper.execution.features.claim_execution import ClaimExecution
from keeper.execution.features.claim_execution import bind as bind_claim
from keeper.execution.features.define_plan import DefinePlan
from keeper.execution.features.define_plan import bind as bind_define_plan
from keeper.execution.features.define_procedure import DefineProcedure
from keeper.execution.features.define_procedure import bind as bind_define_procedure
from keeper.execution.features.dispatch_execution import DispatchExecution
from keeper.execution.features.dispatch_execution import bind as bind_dispatch
from keeper.execution.features.end_execution import EndExecution
from keeper.execution.features.end_execution import bind as bind_end
from keeper.execution.features.report_step import ReportExecutionStep
from keeper.execution.features.report_step import bind as bind_report_step
from keeper.execution.features.report_step_run import ReportStepRun
from keeper.execution.features.report_step_run import bind as bind_report_step_run
from keeper.infrastructure.adapters.in_memory_event_store import InMemoryEventStore
from keeper.infrastructure.deps import make_inmemory_kernel
from keeper.infrastructure.kernel import Kernel
from keeper.infrastructure.ports import AllowAllAuthorize
from keeper.infrastructure.settings import Settings
from keeper.infrastructure.slices.idempotency import hash_command
from keeper.shared.instant import InvalidOccurredAtError, normalize_occurred_at

pytestmark = pytest.mark.unit

_CLOCK_SAYS = datetime(2026, 9, 18, 14, 0, tzinfo=UTC)
"""What the fixed clock returns, which is what a caller who says nothing gets."""

_ENGINE_SAYS = datetime(2019, 3, 4, 9, 30, tzinfo=UTC)
"""A time years before the report, which is what a backfill looks like."""

_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {"exposure_seconds": {"type": "number", "minimum": 0}},
    "required": ["exposure_seconds"],
}


class _FixedClock:
    def now(self) -> datetime:
        return _CLOCK_SAYS


class _Ids:
    def new_id(self) -> UUID:
        return uuid4()


def _kernel() -> Kernel:
    return make_inmemory_kernel(
        settings=Settings(app_env="test"),
        clock=_FixedClock(),
        id_generator=_Ids(),
        authz=AllowAllAuthorize(),  # pyright: ignore[reportArgumentType]
        event_store=InMemoryEventStore(),
    )


async def _an_execution(deps: Kernel) -> tuple[UUID, UUID]:
    """A plan, a procedure acquiring with it, and one dispatch of that.

    All three stamped by the clock, so a reported time asserted below can
    only have come from the command under test.
    """
    plan_id = await bind_define_plan(deps)(
        DefinePlan(name="count", parameters_schema=_SCHEMA),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )
    procedure_id = await bind_define_procedure(deps)(
        DefineProcedure(
            name="one_scan",
            beamline="2-bm",
            steps=(
                AcquireStep(
                    plan_id=plan_id,
                    parameters={"exposure_seconds": 0.25},
                    scopes=("2bmb:det:",),
                ),
            ),
        ),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )
    execution_id = await bind_dispatch(deps)(
        DispatchExecution(procedure_id=procedure_id),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )
    execution = await load_execution(deps.event_store, execution_id)
    assert execution is not None
    return execution_id, execution.steps[0].id


def test_a_naive_timestamp_is_refused() -> None:
    """No offset means no instant, only a reading off somebody's wall.

    Refused rather than assumed to be UTC, because assuming is how a row
    ends up stating a time nobody sent. Postgres would apply the session
    timezone to a naive value written into a `timestamptz` column, and
    nothing downstream could tell that had happened.
    """
    with pytest.raises(InvalidOccurredAtError):
        normalize_occurred_at(datetime(2026, 9, 18, 14, 0))


def test_an_offset_timestamp_comes_back_as_the_same_instant_in_utc() -> None:
    """Converted, not relabelled. 14:32+02:00 is 12:32Z, not 14:32Z."""
    berlin = timezone(timedelta(hours=2))
    normalized = normalize_occurred_at(datetime(2026, 9, 18, 14, 32, tzinfo=berlin))

    assert normalized == datetime(2026, 9, 18, 12, 32, tzinfo=UTC)
    assert normalized.tzinfo is UTC


def test_a_utc_timestamp_passes_through_unchanged() -> None:
    assert normalize_occurred_at(_ENGINE_SAYS) == _ENGINE_SAYS


type _Build = Callable[[UUID, UUID, datetime | None], Any]

_REPORTS: tuple[tuple[str, Any, _Build], ...] = (
    (
        "claim",
        bind_claim,
        lambda eid, _sid, at: ClaimExecution(execution_id=eid, occurred_at=at),
    ),
    (
        "step",
        bind_report_step,
        lambda eid, _sid, at: ReportExecutionStep(
            execution_id=eid, index=0, outcome=StepOutcome.DONE, occurred_at=at
        ),
    ),
    (
        "engine",
        bind_report_step_run,
        lambda eid, sid, at: ReportStepRun(
            execution_id=eid, step_id=sid, reported=EngineReport.STARTED, occurred_at=at
        ),
    ),
    (
        "end",
        bind_end,
        lambda eid, _sid, at: EndExecution(execution_id=eid, occurred_at=at),
    ),
)
"""Every command that records something reported, and how to build each.

A table rather than four tests, because the claim is about all of them at
once. Four separate tests would pass just as well with one slice quietly
dropping the field.

They are ordered as a traversal runs, so each one lands on a record the
one before it left in a state that admits it. Nothing here needs a setup
step of its own for that reason.
"""

_IDS = [label for label, _b, _m in _REPORTS]


@pytest.mark.parametrize(
    ("bind", "build"),
    [(b, m) for _l, b, m in _REPORTS],
    ids=_IDS,
)
async def test_a_report_is_stamped_with_the_time_the_caller_reported(
    bind: Any, build: _Build
) -> None:
    deps = _kernel()
    execution_id, step_id = await _an_execution(deps)

    await bind(deps)(
        build(execution_id, step_id, _ENGINE_SAYS),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )

    rows, _version = await deps.event_store.load(EXECUTION_STREAM_TYPE, execution_id)
    assert rows[-1].occurred_at == _ENGINE_SAYS


@pytest.mark.parametrize(
    ("bind", "build"),
    [(b, m) for _l, b, m in _REPORTS],
    ids=_IDS,
)
async def test_a_report_with_no_reported_time_falls_back_to_the_clock(
    bind: Any, build: _Build
) -> None:
    """The other half of the table, and the one that keeps the field optional.

    A handler that always read the command would stamp `None` here, and a
    handler that always read the clock would pass the test above only if
    the two times happened to match. Running both directions is what pins
    the choice.
    """
    deps = _kernel()
    execution_id, step_id = await _an_execution(deps)

    await bind(deps)(
        build(execution_id, step_id, None),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )

    rows, _version = await deps.event_store.load(EXECUTION_STREAM_TYPE, execution_id)
    assert rows[-1].occurred_at == _CLOCK_SAYS


async def test_a_genesis_in_this_context_takes_no_reported_time_at_all() -> None:
    """The other side of the split, and the reason the table above is short.

    Composing a procedure and dispatching an execution are acts this
    system performs, so there is no earlier moment out in the world for
    the record to be late to. The field is absent from the command rather
    than present and ignored, which is what makes that unmistakable.
    """
    deps = _kernel()
    execution_id, _step_id = await _an_execution(deps)

    rows, _version = await deps.event_store.load(EXECUTION_STREAM_TYPE, execution_id)

    assert rows[0].occurred_at == _CLOCK_SAYS
    assert not hasattr(DispatchExecution(procedure_id=uuid4()), "occurred_at")


async def test_the_recorded_time_is_the_stores_own_whatever_the_caller_claimed() -> None:
    """The claim and the write are two facts, and only one is the caller's.

    This is what makes accepting an unchecked instant safe. A report that
    names a time years in the past still carries a write time of now, so
    a reader can always see the gap rather than having to trust the
    claim.
    """
    deps = _kernel()
    execution_id, _step_id = await _an_execution(deps)

    await bind_claim(deps)(
        ClaimExecution(execution_id=execution_id, occurred_at=_ENGINE_SAYS),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )

    rows, _version = await deps.event_store.load(EXECUTION_STREAM_TYPE, execution_id)
    assert rows[-1].occurred_at == _ENGINE_SAYS
    assert rows[-1].recorded_at != _ENGINE_SAYS


def test_two_spellings_of_one_instant_hash_to_one_command() -> None:
    """The retry bug this field would create without normalising.

    `hash_command` walks the whole command through `asdict` and renders
    what it finds with `str`, so this field joins the idempotency key's
    hash the moment it exists. A caller retrying with `+00:00` where the
    first attempt sent `Z` means the same instant, and without the
    conversion in `__post_init__` the two would hash differently and the
    retry would come back 422 instead of the answer it already had.

    Asserted on the hash rather than through the wrapper, because the
    wrapper would need two full requests to show one string comparison.
    """
    execution_id = uuid4()
    as_utc = EndExecution(execution_id=execution_id, occurred_at=_ENGINE_SAYS)
    as_offset = EndExecution(
        execution_id=execution_id,
        occurred_at=_ENGINE_SAYS.astimezone(timezone(timedelta(hours=2))),
    )

    assert as_utc.occurred_at == as_offset.occurred_at
    assert hash_command(as_utc) == hash_command(as_offset)
