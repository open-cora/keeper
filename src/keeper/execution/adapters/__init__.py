"""Adapters this bounded context supplies to its own read ports.

Eight, in four pairs, and each pair is the two halves of one question.
The ports are declared with the aggregates they summarise, because an
operation, a procedure, an execution and a step summary are all
Execution's to define. The Postgres half of each reads the projection a
deployment maintains; the in-memory half folds the streams when there is
no database to project into.

The step pair is the one that is not purely this context's. It answers
which runs produced data nothing recorded, so both halves have to see
Custody's datasets, and both reach them without importing Custody: the
projection subscribes by event-type string and the fold reads a stream
type by name. An import would close a cycle, because Custody already
reaches in here to check that a step exists before filing against one.

Different from Authority's adapters package, which implements a port
declared in infrastructure. These ports are declared and implemented in
the same context, because nothing outside Execution has any use for an
execution summary.
"""

from keeper.execution.adapters.in_memory_execution_summary_lookup import (
    InMemoryExecutionSummaryLookup,
)
from keeper.execution.adapters.in_memory_operation_summary_lookup import (
    InMemoryOperationSummaryLookup,
)
from keeper.execution.adapters.in_memory_procedure_summary_lookup import (
    InMemoryProcedureSummaryLookup,
)
from keeper.execution.adapters.in_memory_step_summary_lookup import (
    InMemoryStepSummaryLookup,
)
from keeper.execution.adapters.postgres_execution_summary_lookup import (
    PostgresExecutionSummaryLookup,
)
from keeper.execution.adapters.postgres_operation_summary_lookup import (
    PostgresOperationSummaryLookup,
)
from keeper.execution.adapters.postgres_procedure_summary_lookup import (
    PostgresProcedureSummaryLookup,
)
from keeper.execution.adapters.postgres_step_summary_lookup import (
    PostgresStepSummaryLookup,
)

__all__ = [
    "InMemoryExecutionSummaryLookup",
    "InMemoryOperationSummaryLookup",
    "InMemoryProcedureSummaryLookup",
    "InMemoryStepSummaryLookup",
    "PostgresExecutionSummaryLookup",
    "PostgresOperationSummaryLookup",
    "PostgresProcedureSummaryLookup",
    "PostgresStepSummaryLookup",
]
