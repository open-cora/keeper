"""The decision: what defining a plan produces.

Pure. No awaits, no ports, no clock. `now` and `new_id` arrive as
parameters precisely so this function has nothing to invent.
"""

from datetime import datetime
from uuid import UUID

from keeper.execution.aggregates.plan import (
    InvalidPlanParametersSchemaError,
    Plan,
    PlanAlreadyExistsError,
    PlanDefined,
    PlanName,
)
from keeper.execution.features.define_plan.command import DefinePlan
from keeper.shared.json_schema.validation import validate_schema_declaration


def decide(
    state: Plan | None,
    command: DefinePlan,
    *,
    now: datetime,
    new_id: UUID,
) -> list[PlanDefined]:
    """Decide the events produced by defining a plan.

    Invariants:
      - State must be None, or the id already has a history
        -> PlanAlreadyExistsError
      - The name must be non-empty and within the length bound
        -> InvalidPlanNameError
      - The schema must be a Draft 2020-12 document inside the subset
        this system stores -> InvalidPlanParametersSchemaError

    The order is deliberate. The stream check comes first because it is
    about whether this command may be answered at all, and the two
    content checks only mean something once it can be. Between those
    two, the name is checked first because it is the cheaper refusal and
    the easier one for a caller to act on.

    A schema is required rather than optional, so the case of a plan that
    can never refuse a parameter does not arise. See the state module for
    why that cell is closed here and left open in the shared validator.
    """
    if state is not None:
        raise PlanAlreadyExistsError(state.id)
    name = PlanName(command.name)
    validate_schema_declaration(
        command.parameters_schema,
        error_class=InvalidPlanParametersSchemaError,
    )
    return [
        PlanDefined(
            plan_id=new_id,
            plan_name=name.value,
            parameters_schema=command.parameters_schema,
            occurred_at=now,
        )
    ]


__all__ = ["decide"]
