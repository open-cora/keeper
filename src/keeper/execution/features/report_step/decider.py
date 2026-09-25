"""The decision: what reporting one step of an execution produces.

Update-style, so the state comes in already folded and `new_id` is
absent: this command names its stream rather than creating one.

One of four events, chosen by the outcome the caller reported. That is
what puts this slice outside the command-to-event derivation check,
which covers slices emitting exactly one event.

Pure. No awaits, no ports, no clock.
"""

from datetime import datetime

from keeper.execution.aggregates.execution import (
    Execution,
    ExecutionAlreadyEndedError,
    ExecutionNotFoundError,
    ExecutionStepAlreadyReportedError,
    ExecutionStepBroken,
    ExecutionStepDone,
    ExecutionStepOutOfRangeError,
    ExecutionStepRefused,
    ExecutionStepSkipped,
    InvalidStepReportError,
    StepOutcome,
)
from keeper.execution.features.report_step.command import ReportExecutionStep

StepEvent = ExecutionStepDone | ExecutionStepRefused | ExecutionStepBroken | ExecutionStepSkipped
"""The four events this slice can produce, one per outcome."""

_DETAIL_FIELDS: dict[StepOutcome, frozenset[str]] = {
    StepOutcome.DONE: frozenset({"engine_reference"}),
    StepOutcome.REFUSED: frozenset(),
    StepOutcome.BROKEN: frozenset({"cause"}),
    StepOutcome.SKIPPED: frozenset(),
}
"""Which detail fields each outcome is allowed to carry.

A table rather than four branches of ifs, because the stray-field check
is the same question asked four times and the answer is data.

Allowed, not required. `cause` says nothing useful when absent and is
required in its own arm below, where the message can say what is
missing: a break that does not name what was raised is a report a reader
cannot act on. A done step may legitimately carry no engine reference,
because a move opens no run.

Two outcomes now carry nothing. A refusal joined skipped there when the
holder and the overlap came off the step, for the reason `state.py`
gives.
"""


def _supplied(command: ReportExecutionStep) -> frozenset[str]:
    """Which detail fields the caller actually filled in."""
    filled: set[str] = set()
    if command.engine_reference is not None:
        filled.add("engine_reference")
    if command.cause is not None:
        filled.add("cause")
    return frozenset(filled)


def decide(
    state: Execution | None,
    command: ReportExecutionStep,
    *,
    now: datetime,
) -> list[StepEvent]:
    """Decide the event produced by reporting one step.

    Invariants:
      - State must not be None, or no such execution was recorded
        -> ExecutionNotFoundError
      - The execution must not have ended
        -> ExecutionAlreadyEndedError
      - The index must name a step the execution holds
        -> ExecutionStepOutOfRangeError
      - That step must not already have an outcome
        -> ExecutionStepAlreadyReportedError
      - The details must belong to the outcome reported, and the two
        outcomes that cannot be read without one must carry it
        -> InvalidStepReportError

    The order matters for what a caller learns. An execution that has ended is
    refused before the index is looked at, because the execution being closed
    is the more useful fact: a caller told its index was out of range
    would go looking for an off-by-one that is not there.

    A second report for one step is refused rather than absorbed. It is
    either a repeated send, which the idempotency wrapper is there to
    catch first, or two drivers reporting one execution, which is a fault
    worth surfacing rather than resolving by whichever arrived last.

    Nothing here checks that the steps arrive in order, and the omission
    is deliberate. A driver executions sequentially, so out-of-order arrival
    would mean retries overtaking each other on the wire, and a rule
    against it would refuse a report that is perfectly true. What a
    reader needs is which steps have outcomes, which the record answers
    whatever order they landed in.

    Nothing checks the engine reference either. Whatever watches the
    engine records that run on its own schedule, so at this moment the
    run may not exist anywhere yet, and a check would refuse the common
    case. See the conductor's conducting page.
    """
    if state is None:
        raise ExecutionNotFoundError(command.execution_id)
    if state.ended:
        raise ExecutionAlreadyEndedError(command.execution_id)
    if not 0 <= command.index < state.step_count:
        raise ExecutionStepOutOfRangeError(command.execution_id, command.index, state.step_count)
    if state.steps[command.index].is_reported:
        raise ExecutionStepAlreadyReportedError(command.execution_id, command.index)

    stray = _supplied(command) - _DETAIL_FIELDS[command.outcome]
    if stray:
        msg = f"A step reported as {command.outcome} may not carry {', '.join(sorted(stray))}"
        raise InvalidStepReportError(msg)

    match command.outcome:
        case StepOutcome.DONE:
            return [
                ExecutionStepDone(
                    execution_id=command.execution_id,
                    index=command.index,
                    engine_reference=command.engine_reference,
                    occurred_at=now,
                )
            ]
        case StepOutcome.REFUSED:
            return [
                ExecutionStepRefused(
                    execution_id=command.execution_id,
                    index=command.index,
                    occurred_at=now,
                )
            ]
        case StepOutcome.BROKEN:
            if command.cause is None:
                msg = "A broken step must name what was raised"
                raise InvalidStepReportError(msg)
            return [
                ExecutionStepBroken(
                    execution_id=command.execution_id,
                    index=command.index,
                    cause=command.cause,
                    occurred_at=now,
                )
            ]
        case StepOutcome.SKIPPED:
            return [
                ExecutionStepSkipped(
                    execution_id=command.execution_id,
                    index=command.index,
                    occurred_at=now,
                )
            ]


__all__ = ["StepEvent", "decide"]
