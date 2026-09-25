"""The engine's account of one step's run, and what may follow what.

The machine here is the Run aggregate's, one scale down, so the cases
worth writing are the ones that differ: it is addressed by step id rather
than by index, it says nothing about the step's own outcome, and it is
accepted on an execution that has already been closed.
"""

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from keeper.execution.aggregates.execution import (
    DispatchedStep,
    EngineReport,
    EngineState,
    Execution,
    ExecutionDispatched,
    ExecutionEnded,
    ExecutionNotFoundError,
    ExecutionStepDone,
    ExecutionStepEngineAborted,
    ExecutionStepEngineCompleted,
    ExecutionStepEngineFailed,
    ExecutionStepEnginePaused,
    ExecutionStepEngineResumed,
    ExecutionStepEngineStarted,
    ExecutionStepNotFoundError,
    StepOutcome,
    StepRunCannotBeReportedError,
    fold,
)
from keeper.execution.features.report_step_run import ReportStepRun
from keeper.execution.features.report_step_run import decide as decide_run

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 9, 24, 15, 0, tzinfo=UTC)
_WALK = UUID(int=1)
_MOVE = UUID(int=2)
_ACQUIRE = UUID(int=3)


def _walk(*after: object, ended: bool = False) -> Execution:
    events: list[object] = [
        ExecutionDispatched(
            execution_id=_WALK,
            procedure_id=UUID(int=9),
            procedure_name="align_then_scan",
            beamline="2-bm",
            steps=[
                DispatchedStep(
                    id=_MOVE,
                    describes="move 2bmb:m1 to 0.0",
                    procedure_step_id=UUID(int=4),
                ),
                DispatchedStep(
                    id=_ACQUIRE,
                    describes="acquire tomo_scan over 2bmb:det:",
                    procedure_step_id=UUID(int=5),
                ),
            ],
            occurred_at=_NOW,
        ),
        *after,
    ]
    if ended:
        events.append(ExecutionEnded(execution_id=_WALK, occurred_at=_NOW))
    state = fold(events)  # pyright: ignore[reportArgumentType]
    assert state is not None
    return state


def _report(reported: EngineReport, **overrides: object) -> ReportStepRun:
    fields: dict[str, object] = {
        "execution_id": _WALK,
        "step_id": _ACQUIRE,
        "reported": reported,
    }
    fields.update(overrides)
    return ReportStepRun(**fields)  # pyright: ignore[reportArgumentType]


def _started() -> ExecutionStepEngineStarted:
    return ExecutionStepEngineStarted(
        execution_id=_WALK, step_id=_ACQUIRE, engine_reference="uid-7", occurred_at=_NOW
    )


def test_a_start_on_a_step_nothing_has_reported_emits_one_event() -> None:
    events = decide_run(_walk(), _report(EngineReport.STARTED, engine_reference="uid-7"), now=_NOW)
    assert events == [_started()]


def test_a_start_carries_the_engines_name_for_the_run() -> None:
    """Whichever of the two clients lands first is what lets anybody find
    the run, so the reference rides this as well as the done step."""
    (event,) = decide_run(
        _walk(), _report(EngineReport.STARTED, engine_reference="uid-7"), now=_NOW
    )
    assert isinstance(event, ExecutionStepEngineStarted)
    assert event.engine_reference == "uid-7"


def test_a_second_start_on_a_running_step_is_refused() -> None:
    with pytest.raises(StepRunCannotBeReportedError):
        decide_run(_walk(_started()), _report(EngineReport.STARTED), now=_NOW)


@pytest.mark.parametrize(
    ("reported", "expected"),
    [
        (
            EngineReport.PAUSED,
            ExecutionStepEnginePaused(execution_id=_WALK, step_id=_ACQUIRE, occurred_at=_NOW),
        ),
        (
            EngineReport.COMPLETED,
            ExecutionStepEngineCompleted(execution_id=_WALK, step_id=_ACQUIRE, occurred_at=_NOW),
        ),
        (
            EngineReport.ABORTED,
            ExecutionStepEngineAborted(execution_id=_WALK, step_id=_ACQUIRE, occurred_at=_NOW),
        ),
        (
            EngineReport.FAILED,
            ExecutionStepEngineFailed(execution_id=_WALK, step_id=_ACQUIRE, occurred_at=_NOW),
        ),
    ],
    ids=["paused", "completed", "aborted", "failed"],
)
def test_each_report_on_a_running_step_produces_its_own_event(
    reported: EngineReport, expected: object
) -> None:
    assert decide_run(_walk(_started()), _report(reported), now=_NOW) == [expected]


def test_a_resume_follows_a_pause_and_nothing_else() -> None:
    paused = _walk(
        _started(),
        ExecutionStepEnginePaused(execution_id=_WALK, step_id=_ACQUIRE, occurred_at=_NOW),
    )
    assert decide_run(paused, _report(EngineReport.RESUMED), now=_NOW) == [
        ExecutionStepEngineResumed(execution_id=_WALK, step_id=_ACQUIRE, occurred_at=_NOW)
    ]


def test_a_resume_on_a_running_step_is_refused() -> None:
    """Usually means two reporters disagree about what the engine did."""
    with pytest.raises(StepRunCannotBeReportedError):
        decide_run(_walk(_started()), _report(EngineReport.RESUMED), now=_NOW)


@pytest.mark.parametrize(
    "reported",
    [EngineReport.COMPLETED, EngineReport.ABORTED, EngineReport.FAILED],
    ids=["completed", "aborted", "failed"],
)
def test_every_ending_is_reachable_from_paused(reported: EngineReport) -> None:
    """The edge most easily got wrong. A paused run is exactly the one an
    operator aborts."""
    paused = _walk(
        _started(),
        ExecutionStepEnginePaused(execution_id=_WALK, step_id=_ACQUIRE, occurred_at=_NOW),
    )
    assert len(decide_run(paused, _report(reported), now=_NOW)) == 1


def test_a_report_after_an_ending_is_refused_whichever_ending_it_was() -> None:
    """An engine that reported success and then crashed on the way out
    looks exactly like a late failure, and nothing here can tell which
    report was right. Keeping the first makes the disagreement visible."""
    done = _walk(
        _started(),
        ExecutionStepEngineCompleted(execution_id=_WALK, step_id=_ACQUIRE, occurred_at=_NOW),
    )
    with pytest.raises(StepRunCannotBeReportedError):
        decide_run(done, _report(EngineReport.FAILED), now=_NOW)


def test_the_refusal_names_the_state_the_step_is_actually_in() -> None:
    with pytest.raises(StepRunCannotBeReportedError) as caught:
        decide_run(_walk(_started()), _report(EngineReport.RESUMED), now=_NOW)
    assert caught.value.holds is EngineState.RUNNING


def test_a_report_for_a_step_the_walk_does_not_hold_is_refused() -> None:
    with pytest.raises(ExecutionStepNotFoundError):
        decide_run(_walk(), _report(EngineReport.STARTED, step_id=uuid4()), now=_NOW)


def test_a_report_for_a_walk_that_was_never_dispatched_is_refused() -> None:
    with pytest.raises(ExecutionNotFoundError):
        decide_run(None, _report(EngineReport.STARTED), now=_NOW)


def test_an_engine_report_does_not_wait_for_the_driver_to_report_the_step() -> None:
    """The two come from clients that do not know about each other, so
    requiring an order would refuse whichever arrived first."""
    assert len(decide_run(_walk(), _report(EngineReport.STARTED), now=_NOW)) == 1


def test_an_engine_report_is_accepted_after_the_driver_reported_the_step() -> None:
    walked = _walk(
        ExecutionStepDone(execution_id=_WALK, index=1, engine_reference=None, occurred_at=_NOW),
    )
    assert len(decide_run(walked, _report(EngineReport.STARTED), now=_NOW)) == 1


def test_an_engine_report_is_accepted_on_a_walk_that_has_already_closed() -> None:
    """A driver that gave up and closed the execution does not stop the engine
    from having something to say, and that account is the one record of
    what the hardware did."""
    closed = _walk(_started(), ended=True)
    assert decide_run(closed, _report(EngineReport.FAILED), now=_NOW) == [
        ExecutionStepEngineFailed(execution_id=_WALK, step_id=_ACQUIRE, occurred_at=_NOW)
    ]


def test_the_two_accounts_of_one_step_are_kept_apart_on_the_fold() -> None:
    """The measured case: the driver's call returned and the engine says
    the run broke. Collapsing them would make this system pick a winner
    between two claims it cannot check."""
    state = _walk(
        ExecutionStepDone(execution_id=_WALK, index=1, engine_reference=None, occurred_at=_NOW),
        _started(),
        ExecutionStepEngineFailed(execution_id=_WALK, step_id=_ACQUIRE, occurred_at=_NOW),
    )
    step = state.steps[1]
    assert (step.outcome, step.engine_state) == (StepOutcome.DONE, EngineState.FAILED)


def test_a_move_carries_no_engine_state_because_it_opens_no_run() -> None:
    state = _walk(_started())
    assert state.steps[0].engine_state is None
