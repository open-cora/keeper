"""The Operation aggregate: state, events, evolver, and its two read paths."""

from keeper.execution.aggregates.operation.events import (
    OperationDefined,
    OperationEvent,
    from_stored,
    to_payload,
)
from keeper.execution.aggregates.operation.evolver import evolve, fold
from keeper.execution.aggregates.operation.read import OPERATION_STREAM_TYPE, load_operation
from keeper.execution.aggregates.operation.state import (
    OPERATION_NAME_MAX_LENGTH,
    InvalidOperationNameError,
    InvalidOperationParametersSchemaError,
    Operation,
    OperationAlreadyExistsError,
    OperationName,
    OperationNotFoundError,
)
from keeper.execution.aggregates.operation.summary import (
    OperationSummary,
    OperationSummaryLookup,
    OperationSummaryPage,
)

__all__ = [
    "OPERATION_NAME_MAX_LENGTH",
    "OPERATION_STREAM_TYPE",
    "InvalidOperationNameError",
    "InvalidOperationParametersSchemaError",
    "Operation",
    "OperationAlreadyExistsError",
    "OperationDefined",
    "OperationEvent",
    "OperationName",
    "OperationNotFoundError",
    "OperationSummary",
    "OperationSummaryLookup",
    "OperationSummaryPage",
    "evolve",
    "fold",
    "from_stored",
    "load_operation",
    "to_payload",
]
