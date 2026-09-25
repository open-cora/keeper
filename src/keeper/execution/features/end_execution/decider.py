"""The decision: what ending an execution produces.

Update-style, so the state comes in already folded and `new_id` is
absent: this command names its stream rather than creating one.

Pure. No awaits, no ports, no clock.
"""

from datetime import datetime

from keeper.execution.aggregates.execution import (
    Execution,
    ExecutionAlreadyEndedError,
    ExecutionEnded,
    ExecutionNotFoundError,
)
from keeper.execution.features.end_execution.command import EndExecution


def decide(
    state: Execution | None,
    command: EndExecution,
    *,
    now: datetime,
) -> list[ExecutionEnded]:
    """Decide the events produced by ending an execution.

    Invariants:
      - State must not be None, or no such execution was recorded
        -> ExecutionNotFoundError
      - The execution must not have ended already
        -> ExecutionAlreadyEndedError

    An execution with steps still unreported is ended anyway, and refusing
    that would be the wrong rule. A driver that stopped at its first
    failure reports the rest as skipped and then ends, but a driver that
    was killed reports nothing further at all, and the execution that gets
    ended afterwards is exactly the one whose record is incomplete.
    Requiring every step first would mean the only executions that could be
    closed are the ones that did not need closing.

    An already-ended execution is refused rather than absorbed, for the
    reason a run's endings are: two callers each believing they closed a
    live execution should not both be told they did.
    """
    if state is None:
        raise ExecutionNotFoundError(command.execution_id)
    if state.ended:
        raise ExecutionAlreadyEndedError(command.execution_id)
    return [ExecutionEnded(execution_id=command.execution_id, occurred_at=now)]


__all__ = ["decide"]
