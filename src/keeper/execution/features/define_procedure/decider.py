"""The decision: what defining a procedure produces.

Pure. No awaits, no ports, no clock. `now` and `new_id` arrive as
parameters precisely so this function has nothing to invent.
"""

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from keeper.execution.aggregates.procedure import (
    AcquireStep,
    ComposedStep,
    InvalidProcedureParametersError,
    Procedure,
    ProcedureAlreadyExistsError,
    ProcedureBeamline,
    ProcedureDefined,
    ProcedureName,
    validated_steps,
)
from keeper.execution.features.define_procedure.command import DefineProcedure
from keeper.execution.features.define_procedure.context import DefineProcedureContext
from keeper.shared.json_schema.validation import validate_values_against_schema


class _ParametersRejectedError(ValueError):
    """What the shared validator raises here, before the step is named.

    The validator constructs its error class from a reason alone, and the
    refusal this slice publishes also carries which step the reason came
    from. So the reason is caught in this private shape and re-raised in
    the public one, one line below, rather than leaving a caller with a
    procedure told only that one of its acquisitions is wrong.
    """


def decide(
    state: Procedure | None,
    command: DefineProcedure,
    *,
    context: DefineProcedureContext,
    now: datetime,
    new_id: UUID,
    step_ids: Sequence[UUID],
) -> list[ProcedureDefined]:
    """Decide the events produced by defining a procedure.

    Invariants:
      - State must be None, or the id already has a history
        -> ProcedureAlreadyExistsError
      - The name must be non-empty and within the length bound
        -> InvalidProcedureNameError
      - The beamline must be non-empty and within its length bound
        -> InvalidProcedureBeamlineError
      - The step list must be non-empty, within the length bound, and
        every step storable -> InvalidProcedureStepsError
      - Every acquisition's parameters must satisfy the schema its plan
        declares -> InvalidProcedureParametersError

    The order is deliberate and runs cheapest first. The stream check
    comes first because it is about whether this command may be answered
    at all. The name and the beamline are next because they are one
    comparison each. The step list
    is checked whole before any parameters are, so a caller who sent a
    malformed step hears about that rather than about a schema failure
    caused by it.

    That a cited plan exists is NOT checked here. It needs a store, and
    the handler has already refused a procedure citing one that does not.

    An acquisition supplying no parameters at all is accepted whatever
    its plan requires, because the shared validator defers `required` to
    the point the values are acted on. Reporting a step's run has the
    same gap and for the same reason: the check here is carrier-side,
    and the thing finally resolving the values is the engine.

    `step_ids` arrives minted rather than being made here, for the reason
    `new_id` does: this function is pure, and the ids have to be on the
    genesis payload so the fold names the same steps on every replay.
    One per step, in order. A list of the wrong length is a caller bug
    rather than a domain refusal, which is why it raises a plain
    `ValueError` the handler cannot trip. `dispatch_execution` takes the
    same parameter for the same reason.
    """
    if state is not None:
        raise ProcedureAlreadyExistsError(state.id)
    name = ProcedureName(command.name)
    beamline = ProcedureBeamline(command.beamline)
    steps = validated_steps(command.steps)
    if len(step_ids) != len(steps):
        msg = f"a definition needs one id per step: {len(step_ids)} given for {len(steps)} steps"
        raise ValueError(msg)
    for index, step in enumerate(steps):
        if not isinstance(step, AcquireStep):
            continue
        try:
            validate_values_against_schema(
                step.parameters,
                context.plans[step.plan_id].parameters_schema,
                error_class=_ParametersRejectedError,
            )
        except _ParametersRejectedError as rejected:
            raise InvalidProcedureParametersError(index, str(rejected)) from rejected
    return [
        ProcedureDefined(
            procedure_id=new_id,
            procedure_name=name.value,
            beamline=beamline.value,
            steps=tuple(
                ComposedStep(id=step_id, step=step)
                for step_id, step in zip(step_ids, steps, strict=True)
            ),
            occurred_at=now,
        )
    ]


__all__ = ["decide"]
