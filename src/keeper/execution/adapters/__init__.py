"""Adapters this bounded context supplies to its own read port.

Eight, in four pairs, and each pair is the two halves of one question.
The ports are declared with the aggregates they summarise, because a
plan, a procedure, a run and an execution summary are all Execution's to
define. The Postgres half of each reads the projection a deployment
maintains; the in-memory half folds the streams when there is no database
to project into.

Different from Authority's adapters package, which implements a port
declared in infrastructure. This port is declared and implemented in the
same context, because nothing outside Execution has any use for a run
summary.
"""

from keeper.execution.adapters.in_memory_execution_summary_lookup import (
    InMemoryExecutionSummaryLookup,
)
from keeper.execution.adapters.in_memory_plan_summary_lookup import (
    InMemoryPlanSummaryLookup,
)
from keeper.execution.adapters.in_memory_procedure_summary_lookup import (
    InMemoryProcedureSummaryLookup,
)
from keeper.execution.adapters.postgres_execution_summary_lookup import (
    PostgresExecutionSummaryLookup,
)
from keeper.execution.adapters.postgres_plan_summary_lookup import (
    PostgresPlanSummaryLookup,
)
from keeper.execution.adapters.postgres_procedure_summary_lookup import (
    PostgresProcedureSummaryLookup,
)

__all__ = [
    "InMemoryExecutionSummaryLookup",
    "InMemoryPlanSummaryLookup",
    "InMemoryProcedureSummaryLookup",
    "PostgresExecutionSummaryLookup",
    "PostgresPlanSummaryLookup",
    "PostgresProcedureSummaryLookup",
]
