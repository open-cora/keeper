"""Mount the Execution HTTP routes, and map its errors onto status codes.

The handler raises typed errors and knows nothing about HTTP. The
translation lives here, in one place, so the same handler can serve the
MCP surface where those numbers mean nothing.

Four shapes, grouped by the answer they produce:

    400  InvalidPlanNameError
             the name was empty or too long
         InvalidPlanParametersSchemaError
             the schema is not a Draft 2020-12 document this system will
             store
         InvalidProcedureNameError
         InvalidProcedureBeamlineError
         InvalidProcedureStepsError
         InvalidProcedureParametersError
             a procedure was composed with a name, a beamline, a step
             list or a set of acquisition parameters this system will
             not store
         InvalidIdentifierError
             an external reference had an empty or over-long half
         InvalidOccurredAtError
             a reported timestamp carried no timezone, so the instant it
             names cannot be known
         InvalidStepReportError
             a step report carried a detail belonging to a different
             outcome

         All of them say the request was never well-formed, which is a
         different fact from a request that was well-formed and refused.
         Registered through a loop rather than one call each, because the
         next member of this family should be one tuple entry.

         `InvalidIdentifierError` is the odd one: it belongs to a shared
         value object rather than to an aggregate here, so it is not
         named `Invalid<Aggregate><Field>Error` and is not defined in a
         state module. Nothing else registers it, and a shared value
         object refusing its input is still this context's 400 when this
         context is the one that built it.

    403  UnauthorizedError
             the caller is known and refused, which is a different fact
             from 401, where we do not know who is asking

    404  PlanNotFoundError
             the id names no plan this system has a record of, whether
             the caller asked to read one or named one in a procedure
         ProcedureNotFoundError
             a dispatch named a routine nobody composed
         ProcedureStepNotFoundError
             a step of an execution cites a composed step its procedure
             does not hold
         ExecutionNotFoundError
         ExecutionStepNotFoundError
         ExecutionStepOutOfRangeError
             the id names no execution, or that execution holds no such
             step, by id or by index

    409  PlanAlreadyExistsError
         ProcedureAlreadyExistsError
         ExecutionAlreadyExistsError
             a genesis event was asked for on a live stream
         ExecutionAlreadyEndedError
             something arrived for an execution that had closed
         ExecutionCannotBeClaimedError
             a claim arrived for an execution not waiting to be taken up
         ExecutionStepAlreadyReportedError
             a step already has an outcome, and it ends exactly once
         StepRunCannotBeReportedError
             the engine report does not follow the one before it

         Several facts sharing one status, kept as separate classes
         because the caller's next move differs and because the verb in
         the name is the diagnostic. Per R6 in docs/reference/naming.md.

The concurrency and idempotency shapes are NOT here. They are cross-BC
infrastructure errors, registered once at the composition root in
`keeper.api.exception_handlers`.
"""

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from keeper.execution.aggregates.execution import (
    ExecutionAlreadyEndedError,
    ExecutionAlreadyExistsError,
    ExecutionCannotBeClaimedError,
    ExecutionNotFoundError,
    ExecutionStepAlreadyReportedError,
    ExecutionStepNotFoundError,
    ExecutionStepOutOfRangeError,
    InvalidExecutionBeamlineError,
    InvalidExecutionProcedureNameError,
    InvalidExecutionStepsError,
    InvalidStepReportError,
    StepRunCannotBeReportedError,
)
from keeper.execution.aggregates.plan import (
    InvalidPlanNameError,
    InvalidPlanParametersSchemaError,
    PlanAlreadyExistsError,
    PlanNotFoundError,
)
from keeper.execution.aggregates.procedure import (
    InvalidProcedureBeamlineError,
    InvalidProcedureNameError,
    InvalidProcedureParametersError,
    InvalidProcedureStepsError,
    ProcedureAlreadyExistsError,
    ProcedureNotFoundError,
    ProcedureStepNotFoundError,
)
from keeper.execution.errors import UnauthorizedError
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
from keeper.shared.identifier import InvalidIdentifierError
from keeper.shared.instant import InvalidOccurredAtError


async def _handle_bad_request(request: Request, exc: Exception) -> JSONResponse:
    """The request was never well-formed."""
    _ = request
    return JSONResponse(status_code=status.HTTP_400_BAD_REQUEST, content={"detail": str(exc)})


async def _handle_unauthorized(request: Request, exc: Exception) -> JSONResponse:
    """A known caller, refused."""
    _ = request
    return JSONResponse(status_code=status.HTTP_403_FORBIDDEN, content={"detail": str(exc)})


async def _handle_not_found(request: Request, exc: Exception) -> JSONResponse:
    """The id names nothing this system has a record of."""
    _ = request
    return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"detail": str(exc)})


async def _handle_conflict(request: Request, exc: Exception) -> JSONResponse:
    """The request disagrees with state that is already there."""
    _ = request
    return JSONResponse(status_code=status.HTTP_409_CONFLICT, content={"detail": str(exc)})


def register_execution_routes(app: FastAPI) -> None:
    """Include every Execution router and register its exception handlers."""
    app.include_router(define_plan.router)
    app.include_router(get_plan.router)
    app.include_router(list_plans.router)
    app.include_router(dispatch_execution.router)
    app.include_router(claim_execution.router)
    app.include_router(report_step.router)
    app.include_router(report_step_run.router)
    app.include_router(end_execution.router)
    app.include_router(get_execution.router)
    app.include_router(list_executions.router)
    app.include_router(define_procedure.router)
    app.include_router(get_procedure.router)
    app.include_router(list_procedures.router)

    for malformed_cls in (
        InvalidPlanNameError,
        InvalidPlanParametersSchemaError,
        InvalidProcedureNameError,
        InvalidProcedureBeamlineError,
        InvalidProcedureParametersError,
        InvalidProcedureStepsError,
        InvalidIdentifierError,
        InvalidOccurredAtError,
        InvalidStepReportError,
        InvalidExecutionBeamlineError,
        InvalidExecutionProcedureNameError,
        InvalidExecutionStepsError,
    ):
        app.add_exception_handler(malformed_cls, _handle_bad_request)
    app.add_exception_handler(UnauthorizedError, _handle_unauthorized)
    for missing_cls in (
        PlanNotFoundError,
        ProcedureNotFoundError,
        ProcedureStepNotFoundError,
        ExecutionNotFoundError,
        ExecutionStepNotFoundError,
        ExecutionStepOutOfRangeError,
    ):
        app.add_exception_handler(missing_cls, _handle_not_found)
    for conflict_cls in (
        PlanAlreadyExistsError,
        ProcedureAlreadyExistsError,
        ExecutionAlreadyExistsError,
        ExecutionAlreadyEndedError,
        ExecutionCannotBeClaimedError,
        ExecutionStepAlreadyReportedError,
        StepRunCannotBeReportedError,
    ):
        app.add_exception_handler(conflict_cls, _handle_conflict)


__all__ = ["register_execution_routes"]
