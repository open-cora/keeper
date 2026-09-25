"""Execution's read-side projections, and the call that subscribes them.

`register_execution_projections` is re-exported from here, so a caller
writes the package rather than the module it happens to live in. The
context root re-exports it again, which is where the composition root
reads it from.

`PROJECTION_NAME` is deliberately not re-exported. Each projection module
defines one and they are different strings, so a package-level name would
have to pick a winner and every importer would be one rename away from
querying the wrong table. Import it from the module whose table you mean.
"""

from keeper.execution.projections.execution_summary import (
    STEP_EVENT_TYPES,
    ExecutionSummaryProjection,
)
from keeper.execution.projections.plan_summary import PlanSummaryProjection
from keeper.execution.projections.register import register_execution_projections

__all__ = [
    "STEP_EVENT_TYPES",
    "ExecutionSummaryProjection",
    "PlanSummaryProjection",
    "register_execution_projections",
]
