"""The three decisions an execution's write side makes.

One file for three deciders rather than three, because two of them are
four lines and the third is the only one with anything to say. What it
has to say is the detail table: each outcome carries its own fields and
no others, which is the one rule here that a caller can get wrong in a
way the type system does not catch.

The refusal order in the step decider is pinned deliberately. An execution
that has ended is refused before its index is looked at, because a
caller told its index was out of range would go hunting an off-by-one
that is not there.
"""

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from keeper.execution.aggregates.execution import (
    DispatchedStep,
    Execution,
    ExecutionAlreadyEndedError,
    ExecutionAlreadyExistsError,
    ExecutionCannotBeClaimedError,
    ExecutionClaimed,
    ExecutionDispatched,
    ExecutionEnded,
    ExecutionNotFoundError,
    ExecutionStepAlreadyReportedError,
    ExecutionStepBroken,
    ExecutionStepDone,
    ExecutionStepOutOfRangeError,
    ExecutionStepRefused,
    ExecutionStepSkipped,
    InvalidStepReportError,
    StepOutcome,
    evolve,
    fold,
)
from keeper.execution.aggregates.procedure import (
    AcquireStep,
    ComposedStep,
    MoveStep,
    Procedure,
    ProcedureBeamline,
    ProcedureName,
    ProcedureStep,
)
from keeper.execution.features.claim_execution import ClaimExecution
from keeper.execution.features.claim_execution import decide as decide_claim
from keeper.execution.features.dispatch_execution import DispatchExecution, DispatchExecutionContext
from keeper.execution.features.dispatch_execution import decide as decide_dispatch
from keeper.execution.features.end_execution import EndExecution
from keeper.execution.features.end_execution import decide as decide_end
from keeper.execution.features.report_step import ReportExecutionStep
from keeper.execution.features.report_step import decide as decide_step

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 9, 23, 9, 30, tzinfo=UTC)
_ID = UUID(int=1)
_PROCEDURE_ID = UUID(int=7)
_STEP_ID = UUID(int=8)
_PLAN_ID = UUID(int=9)
_STEPS = ("move 2bmb:m1 to 0.0", "acquire tomo_scan", "move 2bmb:m2 to 5.0")


def _live(*, ended: bool = False, reported: tuple[int, ...] = ()) -> Execution:
    events: list[object] = [
        ExecutionDispatched(
            execution_id=_ID,
            procedure_id=_PROCEDURE_ID,
            procedure_name="align_then_scan",
            beamline="2-bm",
            steps=[
                DispatchedStep(id=uuid4(), describes=text, procedure_step_id=uuid4())
                for text in _STEPS
            ],
            occurred_at=_NOW,
        )
    ]
    events.extend(
        ExecutionStepSkipped(execution_id=_ID, index=index, occurred_at=_NOW) for index in reported
    )
    if ended:
        events.append(ExecutionEnded(execution_id=_ID, occurred_at=_NOW))
    state = fold(events)  # pyright: ignore[reportArgumentType]
    assert state is not None
    return state


def _report(**overrides: object) -> ReportExecutionStep:
    fields: dict[str, object] = {
        "execution_id": _ID,
        "index": 0,
        "outcome": StepOutcome.DONE,
    }
    fields.update(overrides)
    return ReportExecutionStep(**fields)  # pyright: ignore[reportArgumentType]


def _procedure(*steps: ProcedureStep, beamline: str = "2-bm") -> DispatchExecutionContext:
    composed = tuple(
        ComposedStep(id=uuid4(), step=step)
        for step in (steps if steps else (MoveStep(record="2bmb:m1", to=0.0),))
    )
    return DispatchExecutionContext(
        procedure=Procedure(
            id=_PROCEDURE_ID,
            name=ProcedureName("align_then_scan"),
            beamline=ProcedureBeamline(beamline),
            steps=composed,
        )
    )


def test_dispatching_a_walk_on_an_empty_stream_emits_one_event() -> None:
    context = _procedure(MoveStep(record="2bmb:m1", to=0.0))
    events = decide_dispatch(
        None,
        DispatchExecution(procedure_id=_PROCEDURE_ID),
        context=context,
        now=_NOW,
        new_id=_ID,
        step_ids=[_STEP_ID],
    )
    assert events == [
        ExecutionDispatched(
            execution_id=_ID,
            procedure_id=_PROCEDURE_ID,
            procedure_name="align_then_scan",
            beamline="2-bm",
            steps=[
                DispatchedStep(
                    id=_STEP_ID,
                    describes="move 2bmb:m1 to 0.0",
                    procedure_step_id=context.procedure.steps[0].id,
                )
            ],
            occurred_at=_NOW,
        )
    ]


def test_dispatching_with_the_wrong_number_of_step_ids_is_a_caller_bug() -> None:
    """Not a domain refusal. The handler mints one id per step off the
    procedure it just read, so a mismatch means that handler is wrong
    rather than that a caller sent something bad."""
    with pytest.raises(ValueError, match="one id per step"):
        decide_dispatch(
            None,
            DispatchExecution(procedure_id=_PROCEDURE_ID),
            context=_procedure(
                MoveStep(record="2bmb:m1", to=0.0),
                MoveStep(record="2bmb:m2", to=5.0),
            ),
            now=_NOW,
            new_id=_ID,
            step_ids=[_STEP_ID],
        )


def test_the_dispatched_walk_copies_the_procedures_steps_in_order() -> None:
    """The execution's own record has to be readable after the thing driving
    it has gone, so the steps are copied rather than only cited."""
    events = decide_dispatch(
        None,
        DispatchExecution(procedure_id=_PROCEDURE_ID),
        context=_procedure(
            MoveStep(record="2bmb:m1", to=0.0),
            MoveStep(record="2bmb:m2", to=5.0),
        ),
        now=_NOW,
        new_id=_ID,
        step_ids=[uuid4(), uuid4()],
    )
    assert [step.describes for step in events[0].steps] == [
        "move 2bmb:m1 to 0.0",
        "move 2bmb:m2 to 5.0",
    ]


def test_every_dispatched_step_cites_the_composed_step_it_came_from() -> None:
    """The one machine-readable thing a step carries, beside its id.

    Counsel joins a proposal to the step that took it and compares the
    plan that step runs; without this the comparison would have to index
    into the procedure's own list, which is a correspondence nothing
    checks. A move cites one too: what a step was asked to do is the
    definition's to say, whichever kind it is.
    """
    context = _procedure(
        MoveStep(record="2bmb:m1", to=0.0),
        AcquireStep(plan_id=_PLAN_ID, parameters={}, scopes=("2bmb:det:",)),
    )
    events = decide_dispatch(
        None,
        DispatchExecution(procedure_id=_PROCEDURE_ID),
        context=context,
        now=_NOW,
        new_id=_ID,
        step_ids=[uuid4(), uuid4()],
    )
    assert [step.procedure_step_id for step in events[0].steps] == [
        composed.id for composed in context.procedure.steps
    ]


def test_a_dispatch_copies_the_beamline_the_procedure_was_composed_for() -> None:
    """Copied rather than cited, because the work intake filters a page
    of executions on it and a reference cannot be followed per row."""
    events = decide_dispatch(
        None,
        DispatchExecution(procedure_id=_PROCEDURE_ID),
        context=_procedure(MoveStep(record="7bmb:m1", to=0.0), beamline="7-bm"),
        now=_NOW,
        new_id=_ID,
        step_ids=[_STEP_ID],
    )
    assert events[0].beamline == "7-bm"


def test_a_dispatched_step_is_named_apart_from_the_step_it_cites() -> None:
    """Two ids on one step, and they are not interchangeable: one names
    this traversal's step and the other the definition every traversal of
    the procedure shares."""
    context = _procedure(MoveStep(record="2bmb:m1", to=0.0))
    events = decide_dispatch(
        None,
        DispatchExecution(procedure_id=_PROCEDURE_ID),
        context=context,
        now=_NOW,
        new_id=_ID,
        step_ids=[_STEP_ID],
    )
    (step,) = events[0].steps
    assert step.id == _STEP_ID
    assert step.procedure_step_id != _STEP_ID


def test_dispatching_a_walk_onto_a_live_stream_is_refused() -> None:
    with pytest.raises(ExecutionAlreadyExistsError):
        decide_dispatch(
            _live(),
            DispatchExecution(procedure_id=_PROCEDURE_ID),
            context=_procedure(),
            now=_NOW,
            new_id=_ID,
            step_ids=[uuid4()],
        )


def test_claiming_a_dispatched_walk_emits_one_event() -> None:
    events = decide_claim(_live(), ClaimExecution(execution_id=_ID), now=_NOW)
    assert events == [ExecutionClaimed(execution_id=_ID, occurred_at=_NOW)]


def test_claiming_a_walk_twice_is_refused() -> None:
    """Two drivers each believing they own one traversal. Nothing here
    can stop the second from moving a motor; refusing keeps the
    disagreement in the log rather than only at the beamline."""
    claimed = evolve(_live(), ExecutionClaimed(execution_id=_ID, occurred_at=_NOW))
    with pytest.raises(ExecutionCannotBeClaimedError):
        decide_claim(claimed, ClaimExecution(execution_id=_ID), now=_NOW)


def test_claiming_a_walk_that_was_never_dispatched_is_refused() -> None:
    with pytest.raises(ExecutionNotFoundError):
        decide_claim(None, ClaimExecution(execution_id=_ID), now=_NOW)


def test_claiming_a_walk_that_already_ended_is_refused() -> None:
    with pytest.raises(ExecutionCannotBeClaimedError):
        decide_claim(_live(ended=True), ClaimExecution(execution_id=_ID), now=_NOW)


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        (
            _report(outcome=StepOutcome.DONE, engine_reference="uid-7"),
            ExecutionStepDone(
                execution_id=_ID, index=0, engine_reference="uid-7", occurred_at=_NOW
            ),
        ),
        (
            _report(outcome=StepOutcome.DONE),
            ExecutionStepDone(execution_id=_ID, index=0, engine_reference=None, occurred_at=_NOW),
        ),
        (
            _report(outcome=StepOutcome.REFUSED),
            ExecutionStepRefused(execution_id=_ID, index=0, occurred_at=_NOW),
        ),
        (
            _report(outcome=StepOutcome.BROKEN, cause="TimeoutError"),
            ExecutionStepBroken(execution_id=_ID, index=0, cause="TimeoutError", occurred_at=_NOW),
        ),
        (
            _report(outcome=StepOutcome.SKIPPED),
            ExecutionStepSkipped(execution_id=_ID, index=0, occurred_at=_NOW),
        ),
    ],
    ids=["done with a run", "done with no run", "refused", "broken", "skipped"],
)
def test_each_outcome_produces_its_own_event(
    command: ReportExecutionStep, expected: object
) -> None:
    assert decide_step(_live(), command, now=_NOW) == [expected]


@pytest.mark.parametrize(
    ("command", "stray"),
    [
        (_report(outcome=StepOutcome.DONE, cause="TimeoutError"), "cause"),
        (_report(outcome=StepOutcome.SKIPPED, engine_reference="uid-7"), "engine_reference"),
        (_report(outcome=StepOutcome.REFUSED, cause="TimeoutError"), "cause"),
        (_report(outcome=StepOutcome.REFUSED, engine_reference="uid-7"), "engine_reference"),
    ],
    ids=["done with a cause", "skipped with a run", "refused with a cause", "refused with a run"],
)
def test_a_detail_from_another_outcome_is_refused(command: ReportExecutionStep, stray: str) -> None:
    with pytest.raises(InvalidStepReportError, match=stray):
        decide_step(_live(), command, now=_NOW)


def test_a_break_that_does_not_name_what_was_raised_is_refused() -> None:
    with pytest.raises(InvalidStepReportError, match="raised"):
        decide_step(_live(), _report(outcome=StepOutcome.BROKEN), now=_NOW)


def test_reporting_a_step_of_a_walk_that_was_never_recorded_is_refused() -> None:
    with pytest.raises(ExecutionNotFoundError):
        decide_step(None, _report(), now=_NOW)


@pytest.mark.parametrize("index", [-1, 3, 99], ids=["before", "just past", "far past"])
def test_reporting_a_step_the_walk_does_not_have_is_refused(index: int) -> None:
    with pytest.raises(ExecutionStepOutOfRangeError):
        decide_step(_live(), _report(index=index), now=_NOW)


def test_reporting_a_step_twice_is_refused_rather_than_taken_as_a_correction() -> None:
    with pytest.raises(ExecutionStepAlreadyReportedError):
        decide_step(_live(reported=(1,)), _report(index=1), now=_NOW)


def test_steps_out_of_order_are_accepted() -> None:
    """A driver executions in order, so out-of-order arrival means retries raced."""
    events = decide_step(_live(), _report(index=2), now=_NOW)
    assert events == [
        ExecutionStepDone(execution_id=_ID, index=2, engine_reference=None, occurred_at=_NOW)
    ]


def test_an_ended_walk_refuses_a_step_before_looking_at_its_index() -> None:
    """The closed execution is the useful fact; an index complaint would mislead."""
    with pytest.raises(ExecutionAlreadyEndedError):
        decide_step(_live(ended=True), _report(index=99), now=_NOW)


def test_ending_a_walk_that_reported_every_step_emits_one_event() -> None:
    assert decide_end(_live(reported=(0, 1, 2)), EndExecution(execution_id=_ID), now=_NOW) == [
        ExecutionEnded(execution_id=_ID, occurred_at=_NOW)
    ]


def test_ending_a_walk_whose_steps_are_unreported_is_allowed() -> None:
    """Otherwise the only executions that could be closed are the ones not needing it."""
    assert decide_end(_live(), EndExecution(execution_id=_ID), now=_NOW) == [
        ExecutionEnded(execution_id=_ID, occurred_at=_NOW)
    ]


def test_ending_a_walk_that_was_never_recorded_is_refused() -> None:
    with pytest.raises(ExecutionNotFoundError):
        decide_end(None, EndExecution(execution_id=uuid4()), now=_NOW)


def test_ending_a_walk_twice_is_refused() -> None:
    with pytest.raises(ExecutionAlreadyEndedError):
        decide_end(_live(ended=True), EndExecution(execution_id=_ID), now=_NOW)
