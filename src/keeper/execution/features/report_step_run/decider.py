"""The decision: what relaying an engine's account of a step produces.

Pure. No awaits, no ports, no clock. `now` arrives as a parameter
precisely so this function has nothing to invent.
"""

from datetime import datetime

from keeper.execution.aggregates.execution import (
    EngineReport,
    EngineState,
    Execution,
    ExecutionNotFoundError,
    ExecutionStep,
    ExecutionStepEngineAborted,
    ExecutionStepEngineCompleted,
    ExecutionStepEngineFailed,
    ExecutionStepEnginePaused,
    ExecutionStepEngineResumed,
    ExecutionStepEngineStarted,
    ExecutionStepNotFoundError,
    StepRunCannotBeReportedError,
)
from keeper.execution.features.report_step_run.command import ReportStepRun

StepRunEvent = (
    ExecutionStepEngineStarted
    | ExecutionStepEnginePaused
    | ExecutionStepEngineResumed
    | ExecutionStepEngineCompleted
    | ExecutionStepEngineAborted
    | ExecutionStepEngineFailed
)
"""The six events this slice can produce, one per thing an engine did."""

_FOLLOWS: dict[EngineReport, frozenset[EngineState | None]] = {
    EngineReport.STARTED: frozenset({None}),
    EngineReport.PAUSED: frozenset({EngineState.RUNNING}),
    EngineReport.RESUMED: frozenset({EngineState.PAUSED}),
    EngineReport.COMPLETED: frozenset({EngineState.RUNNING, EngineState.PAUSED}),
    EngineReport.ABORTED: frozenset({EngineState.RUNNING, EngineState.PAUSED}),
    EngineReport.FAILED: frozenset({EngineState.RUNNING, EngineState.PAUSED}),
}
"""Which engine states each report may follow.

A table rather than six branches of ifs, because the question is the same
one asked six times and the answer is data.

`None` appears once, against a start, which is what makes a start the
genesis of this second account and every other report a transition on it.
The three terminals appear in no value, so nothing follows an ending: an
engine that reported success and then crashed on the way out looks
exactly like a late failure, and this system cannot tell which report was
right. Keeping the first and refusing the second makes the disagreement
visible where accepting it would overwrite a claim somebody already made.

All three endings are reachable from `PAUSED` as well as from `RUNNING`,
which is the edge most easily got wrong. A paused run is exactly the one
an operator aborts.
"""


def _find(state: Execution, command: ReportStepRun) -> ExecutionStep:
    for step in state.steps:
        if step.id == command.step_id:
            return step
    raise ExecutionStepNotFoundError(state.id, command.step_id)


def decide(
    state: Execution | None,
    command: ReportStepRun,
    *,
    now: datetime,
) -> list[StepRunEvent]:
    """Decide the events produced by relaying an engine's account.

    Invariants:
      - State must not be None, or no such execution was dispatched
        -> ExecutionNotFoundError
      - The execution must hold a step with that id
        -> ExecutionStepNotFoundError
      - The report must follow the engine state already recorded
        -> StepRunCannotBeReportedError

    What is deliberately NOT checked is the step's own outcome. A driver
    may report its call returning before or after the engine reports the
    run ending, because the two come from different clients that do not
    know about each other, and requiring an order would refuse whichever
    happened to arrive first.

    An execution that has ended is not checked either, and that is the same
    decision. An engine's account of a run can arrive after a driver gave
    up and closed the execution; refusing it would throw away the one record
    that says what the hardware actually did.
    """
    if state is None:
        raise ExecutionNotFoundError(command.execution_id)
    step = _find(state, command)
    if step.engine_state not in _FOLLOWS[command.reported]:
        raise StepRunCannotBeReportedError(
            command.step_id, holds=step.engine_state, got=command.reported.value
        )
    match command.reported:
        case EngineReport.STARTED:
            return [
                ExecutionStepEngineStarted(
                    execution_id=command.execution_id,
                    step_id=command.step_id,
                    engine_reference=command.engine_reference,
                    occurred_at=now,
                )
            ]
        case EngineReport.PAUSED:
            return [
                ExecutionStepEnginePaused(
                    execution_id=command.execution_id, step_id=command.step_id, occurred_at=now
                )
            ]
        case EngineReport.RESUMED:
            return [
                ExecutionStepEngineResumed(
                    execution_id=command.execution_id, step_id=command.step_id, occurred_at=now
                )
            ]
        case EngineReport.COMPLETED:
            return [
                ExecutionStepEngineCompleted(
                    execution_id=command.execution_id, step_id=command.step_id, occurred_at=now
                )
            ]
        case EngineReport.ABORTED:
            return [
                ExecutionStepEngineAborted(
                    execution_id=command.execution_id, step_id=command.step_id, occurred_at=now
                )
            ]
        case EngineReport.FAILED:
            return [
                ExecutionStepEngineFailed(
                    execution_id=command.execution_id, step_id=command.step_id, occurred_at=now
                )
            ]


__all__ = ["StepRunEvent", "decide"]
