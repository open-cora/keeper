"""The decision: what dispatching an execution produces.

Pure. No awaits, no ports, no clock. `now` and `new_id` arrive as
parameters precisely so this function has nothing to invent.
"""

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from keeper.execution.aggregates.execution import (
    DispatchedStep,
    Execution,
    ExecutionAlreadyExistsError,
    ExecutionBeamline,
    ExecutionDispatched,
    ExecutionProcedureName,
    validated_steps,
)
from keeper.execution.aggregates.procedure import describes
from keeper.execution.features.dispatch_execution.command import DispatchExecution
from keeper.execution.features.dispatch_execution.context import DispatchExecutionContext


def decide(
    state: Execution | None,
    command: DispatchExecution,
    *,
    context: DispatchExecutionContext,
    now: datetime,
    new_id: UUID,
    step_ids: Sequence[UUID],
) -> list[ExecutionDispatched]:
    """Decide the events produced by dispatching an execution.

    Invariants:
      - State must be None, or the id already has a history
        -> ExecutionAlreadyExistsError
      - The procedure's name must be within the execution's bound
        -> InvalidExecutionProcedureNameError
      - The procedure's beamline must be within the execution's bound
        -> InvalidExecutionBeamlineError
      - The rendered step list must be non-empty and bounded
        -> InvalidExecutionStepsError

    The value checks look redundant, because a procedure enforced its own
    bounds at definition and they are the same numbers. They are not
    redundant: the bounds are declared twice, on two aggregates, and
    nothing stops one moving. Running them here is what keeps an execution's
    record within the execution's own limits whatever the procedure's turn out
    to be, and the evolver runs them again on the way back out.

    That the procedure exists is NOT checked here. Discovering an absence
    needs the store, and the handler has already refused a dispatch
    naming one that does not.

    `step_ids` arrives minted rather than being made here, for the reason
    `new_id` does: this function is pure, and the ids have to be on the
    genesis payload so the fold produces the same steps on every replay.
    One per step, in order, and a list of the wrong length is a caller
    bug rather than a domain refusal, so the zip below is checked with an
    assertion the handler cannot trip.
    """
    if state is not None:
        raise ExecutionAlreadyExistsError(state.id)
    composed = context.procedure.steps
    if len(step_ids) != len(composed):
        msg = f"dispatch needs one id per step: {len(step_ids)} given for {len(composed)} steps"
        raise ValueError(msg)
    return [
        ExecutionDispatched(
            execution_id=new_id,
            procedure_id=command.procedure_id,
            procedure_name=ExecutionProcedureName(value=context.procedure.name.value).value,
            beamline=ExecutionBeamline(value=context.procedure.beamline.value).value,
            steps=list(
                validated_steps(
                    tuple(
                        DispatchedStep(
                            id=step_id,
                            describes=describes(step.step),
                            procedure_step_id=step.id,
                        )
                        for step_id, step in zip(step_ids, composed, strict=True)
                    )
                )
            ),
            occurred_at=now,
        )
    ]


__all__ = ["decide"]
