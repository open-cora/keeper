"""Compose the Execution handlers from the process-wide dependencies.

`wire_execution(deps)` runs once during startup and the bundle it returns
is attached to the app. Routes and MCP tools both pull their handler out
of that bundle, which is what keeps the two surfaces calling the same
code rather than two copies of it.

Wrapping order, innermost first:

  1. bind          the bare handler
  2. idempotency   a replayed key returns the first answer instead of
                   defining a second plan
  3. tracing       one span per call, whether or not the key hit cache

Idempotency wraps inside tracing on purpose: a cache hit is still a call
somebody made and should still appear in a trace.

The reads go without the middle layer, because a read has nothing to make
idempotent, and so do the execution's own transitions: a replayed claim,
step report, engine report or ending is already refused by the domain, so
the wrapper would buy a friendlier status code for a retry rather than
prevent a second write.

Tracing wraps all of them. A query that is slow or failing is as much a
fact about the system as a write that is, and the reads that go to a
table rather than to a stream are the ones most likely to become the slow
ones.

Three slices take more than the kernel. `list_plans`, `list_procedures`
and `list_executions` read a projection, which the kernel cannot hold
because the kernel is declared in infrastructure and an execution summary
is Execution's own idea, so this module picks the implementation and
passes it in. That is the first deployment-shaped choice made in a
bounded context rather than in `build_kernel`, and it is here because
this is where composition belongs once the thing being composed is a
context's own.

The three slices that mint an id take the idempotency wrapper: defining a
plan, defining a procedure, and dispatching an execution. In each of them
the server mints the id, so a retry with no key would leave a second
record of one act. Everything else names a record that already exists,
and the domain refuses the second write on its own.
"""

from dataclasses import dataclass
from uuid import UUID

from keeper.execution.adapters import (
    InMemoryExecutionSummaryLookup,
    InMemoryPlanSummaryLookup,
    InMemoryProcedureSummaryLookup,
    PostgresExecutionSummaryLookup,
    PostgresPlanSummaryLookup,
    PostgresProcedureSummaryLookup,
)
from keeper.execution.aggregates.execution.summary import ExecutionSummaryLookup
from keeper.execution.aggregates.plan.summary import PlanSummaryLookup
from keeper.execution.aggregates.procedure.summary import ProcedureSummaryLookup
from keeper.execution.features import (
    claim_execution,
    define_plan,
    define_procedure,
    dispatch_execution,
    end_execution,
    get_execution,
    get_plan,
    get_procedure,
    list_executions,
    list_plans,
    list_procedures,
    report_step,
    report_step_run,
)
from keeper.infrastructure.adapters.in_memory_event_store import InMemoryEventStore
from keeper.infrastructure.kernel import Kernel
from keeper.infrastructure.observability import with_tracing
from keeper.infrastructure.slices.idempotency import with_idempotency

_BC = "execution"


class UnreadableSummariesError(RuntimeError):
    """Startup found no way to read this context's summaries.

    Raised when there is neither a connection pool nor the in-memory event
    store, which is a combination no supported environment produces and a
    new adapter could. Failing here rather than at the first request is
    the point: a deployment that cannot answer a query should not finish
    booting and look healthy.
    """

    def __init__(self, event_store: str) -> None:
        super().__init__(
            f"No pool and no in-memory event store ({event_store}), so nothing "
            "can answer a summary query"
        )
        self.event_store = event_store


@dataclass(frozen=True)
class ExecutionHandlers:
    """The bundle, one field per slice."""

    define_plan: define_plan.IdempotentHandler
    get_plan: get_plan.Handler
    list_plans: list_plans.Handler
    define_procedure: define_procedure.IdempotentHandler
    get_procedure: get_procedure.Handler
    list_procedures: list_procedures.Handler
    dispatch_execution: dispatch_execution.IdempotentHandler
    claim_execution: claim_execution.Handler
    report_step: report_step.Handler
    report_step_run: report_step_run.Handler
    end_execution: end_execution.Handler
    get_execution: get_execution.Handler
    list_executions: list_executions.Handler


def _execution_summary_lookup(deps: Kernel) -> ExecutionSummaryLookup:
    """Pick the read adapter for executions, the same way and for the same reason.

    A third near-identical picker rather than one generic one. What they
    share is three lines of branching; what differs is the pair of
    classes, which is the whole of what each one is for.
    """
    if deps.pool is not None:
        return PostgresExecutionSummaryLookup(deps.pool)
    if isinstance(deps.event_store, InMemoryEventStore):
        return InMemoryExecutionSummaryLookup(deps.event_store)
    raise UnreadableSummariesError(type(deps.event_store).__name__)


def _plan_summary_lookup(deps: Kernel) -> PlanSummaryLookup:
    """Pick the read adapter for plans, the same way and for the same reason.

    Two nearly identical functions rather than one generic picker. What
    they share is three lines of branching; what differs is the pair of
    classes, which is the whole of what each one is for. A shared version
    would take those as arguments and read as a factory for factories.
    """
    if deps.pool is not None:
        return PostgresPlanSummaryLookup(deps.pool)
    if isinstance(deps.event_store, InMemoryEventStore):
        return InMemoryPlanSummaryLookup(deps.event_store)
    raise UnreadableSummariesError(type(deps.event_store).__name__)


def _procedure_summary_lookup(deps: Kernel) -> ProcedureSummaryLookup:
    """Pick the read adapter for procedures, the same way and for the same reason."""
    if deps.pool is not None:
        return PostgresProcedureSummaryLookup(deps.pool)
    if isinstance(deps.event_store, InMemoryEventStore):
        return InMemoryProcedureSummaryLookup(deps.event_store)
    raise UnreadableSummariesError(type(deps.event_store).__name__)


def wire_execution(deps: Kernel) -> ExecutionHandlers:
    """Build the Execution handlers."""
    return ExecutionHandlers(
        define_plan=with_tracing(
            with_idempotency(
                define_plan.bind(deps),
                deps.idempotency_store,
                command_name="DefinePlan",
                serialize_result=str,
                deserialize_result=lambda raw: UUID(str(raw)),
                lock_stale_seconds=deps.settings.idempotency_lock_stale_seconds,
            ),
            command_name="DefinePlan",
            bc=_BC,
        ),
        get_plan=with_tracing(
            get_plan.bind(deps),
            command_name="GetPlan",
            bc=_BC,
        ),
        list_plans=with_tracing(
            list_plans.bind(deps, _plan_summary_lookup(deps)),
            command_name="ListPlans",
            bc=_BC,
        ),
        define_procedure=with_tracing(
            with_idempotency(
                define_procedure.bind(deps),
                deps.idempotency_store,
                command_name="DefineProcedure",
                serialize_result=str,
                deserialize_result=lambda raw: UUID(str(raw)),
                lock_stale_seconds=deps.settings.idempotency_lock_stale_seconds,
            ),
            command_name="DefineProcedure",
            bc=_BC,
        ),
        get_procedure=with_tracing(
            get_procedure.bind(deps),
            command_name="GetProcedure",
            bc=_BC,
        ),
        list_procedures=with_tracing(
            list_procedures.bind(deps, _procedure_summary_lookup(deps)),
            command_name="ListProcedures",
            bc=_BC,
        ),
        dispatch_execution=with_tracing(
            with_idempotency(
                dispatch_execution.bind(deps),
                deps.idempotency_store,
                command_name="DispatchExecution",
                serialize_result=str,
                deserialize_result=lambda raw: UUID(str(raw)),
                lock_stale_seconds=deps.settings.idempotency_lock_stale_seconds,
            ),
            command_name="DispatchExecution",
            bc=_BC,
        ),
        report_step=with_tracing(
            report_step.bind(deps),
            command_name="ReportExecutionStep",
            bc=_BC,
        ),
        report_step_run=with_tracing(
            report_step_run.bind(deps),
            command_name="ReportStepRun",
            bc=_BC,
        ),
        claim_execution=with_tracing(
            claim_execution.bind(deps),
            command_name="ClaimExecution",
            bc=_BC,
        ),
        end_execution=with_tracing(
            end_execution.bind(deps),
            command_name="EndExecution",
            bc=_BC,
        ),
        get_execution=with_tracing(
            get_execution.bind(deps),
            command_name="GetExecution",
            bc=_BC,
        ),
        list_executions=with_tracing(
            list_executions.bind(deps, _execution_summary_lookup(deps)),
            command_name="ListExecutions",
            bc=_BC,
        ),
    )


__all__ = ["ExecutionHandlers", "UnreadableSummariesError", "wire_execution"]
