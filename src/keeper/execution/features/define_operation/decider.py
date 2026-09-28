"""The decision: what defining an operation produces.

Pure. No awaits, no ports, no clock. `now` and `new_id` arrive as
parameters precisely so this function has nothing to invent.
"""

from datetime import datetime
from uuid import UUID

from keeper.execution.aggregates.operation import (
    InvalidOperationParametersSchemaError,
    Operation,
    OperationAlreadyExistsError,
    OperationDefined,
    OperationName,
)
from keeper.execution.features.define_operation.command import DefineOperation
from keeper.shared.json_schema.validation import validate_schema_declaration


def decide(
    state: Operation | None,
    command: DefineOperation,
    *,
    now: datetime,
    new_id: UUID,
) -> list[OperationDefined]:
    """Decide the events produced by defining an operation.

    Invariants:
      - State must be None, or the id already has a history
        -> OperationAlreadyExistsError
      - The name must be non-empty and within the length bound
        -> InvalidOperationNameError
      - The schema must be a Draft 2020-12 document inside the subset
        this system stores -> InvalidOperationParametersSchemaError

    The order is deliberate. The stream check comes first because it is
    about whether this command may be answered at all, and the two
    content checks only mean something once it can be. Between those
    two, the name is checked first because it is the cheaper refusal and
    the easier one for a caller to act on.

    A schema is required rather than optional, so the case of an operation that
    can never refuse a parameter does not arise. See the state module for
    why that cell is closed here and left open in the shared validator.
    """
    if state is not None:
        raise OperationAlreadyExistsError(state.id)
    name = OperationName(command.name)
    validate_schema_declaration(
        command.parameters_schema,
        error_class=InvalidOperationParametersSchemaError,
    )
    return [
        OperationDefined(
            operation_id=new_id,
            operation_name=name.value,
            parameters_schema=command.parameters_schema,
            occurred_at=now,
        )
    ]


__all__ = ["decide"]
