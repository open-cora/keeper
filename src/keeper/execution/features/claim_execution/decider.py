"""The decision: what claiming an execution produces.

Pure. No awaits, no ports, no clock. `now` arrives as a parameter
precisely so this function has nothing to invent.
"""

from datetime import datetime

from keeper.execution.aggregates.execution import (
    Execution,
    ExecutionCannotBeClaimedError,
    ExecutionClaimed,
    ExecutionNotFoundError,
    ExecutionStatus,
)
from keeper.execution.features.claim_execution.command import ClaimExecution


def decide(
    state: Execution | None,
    command: ClaimExecution,
    *,
    now: datetime,
) -> list[ExecutionClaimed]:
    """Decide the events produced by claiming an execution.

    Invariants:
      - State must not be None, or no such execution was dispatched
        -> ExecutionNotFoundError
      - The execution must be dispatched and not yet taken up
        -> ExecutionCannotBeClaimedError

    Refused from every status but `DISPATCHED`, which makes this the only
    command on this stream that refuses from a live status as well as
    from the terminal one. The pair a run offers for pause and resume is
    the precedent, and the reason is the same: the two live refusals mean
    different things and a caller needs the status to tell them apart.

    A second claim is the one worth stating. Two drivers each believing
    they own one traversal is the failure the status exists to make
    visible, and nothing here can stop the second one from moving a
    motor. What it can do is refuse to record that the execution was taken up
    twice, so the disagreement ends up in the log rather than only at the
    beamline.

    Claiming is not a gate on reporting. A driver that reports a step
    without claiming first moves the execution straight from dispatched to
    running, and that is allowed: a claim says who has the work, and
    refusing the report would lose a fact this system was told in order
    to enforce an ordering the log does not have.
    """
    if state is None:
        raise ExecutionNotFoundError(command.execution_id)
    if state.status is not ExecutionStatus.DISPATCHED:
        raise ExecutionCannotBeClaimedError(command.execution_id, state.status)
    return [ExecutionClaimed(execution_id=command.execution_id, occurred_at=now)]


__all__ = ["decide"]
