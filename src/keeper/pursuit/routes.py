"""Mount the Pursuit HTTP routes, and map its errors onto status codes.

The handler raises typed errors and knows nothing about HTTP. The
translation lives here, in one place, so the same handler can serve the
MCP surface where those numbers mean nothing.

Four shapes:

    400  InvalidPursuitGoalError
         InvalidPursuitBeamlineError
             the text is empty, whitespace-only, or too long
         InvalidPursuitScopesError
             there were none, one was empty, or there were too many
         InvalidPursuitBudgetError
             it bounded nothing, or a limit was not positive
         InvalidPursuitChargeError
             the amount was not positive, the dimension is one this
             system counts for itself, or the pursuit was never bounded
             in it
         InvalidCursorError
             a page cursor did not decode. Registered in
             `keeper.infrastructure`, not here, because every listing in
             the tree raises the same one

    403  UnauthorizedError
             the caller is known and refused, which is a different fact
             from 401, where we do not know who is asking. Registered in
             `keeper.api.exception_handlers` rather than here: the class
             is shared by every context, so one mapping serves them all

    404  PursuitNotFoundError
             the id names no pursuit this system has a record of

    409  PursuitAlreadyExistsError
             a genesis event was asked for on a live stream
         PursuitCannotBeWithdrawnError
             the pursuit had already stopped
         PursuitRoundCannotBeOpenedError
             the pursuit has stopped, has spent a budget dimension, or
             has already asked about that execution
         PursuitRoundCannotBeClosedError
             the pursuit is not running, there is no such round, it has
             already closed, or its inquiry carries no answer yet
         PursuitCannotBeResumedError
             the pursuit was running or had stopped

Four more this context relies on and does not register.
`ExecutionNotFoundError` reaches a Pursuit route when a round names an
execution that is not there, `InvalidOccurredAtError` when a charge
carries a naive timestamp, and `OperationNotFoundError` when a round closing on
a proposal cannot find the operation behind it. All three are Execution's.
`InquiryNotFoundError` and `ProposalNotFoundError` are Counsel's, and
reach a route here for the same reason: a round cites records in two other
contexts and either could be gone. FastAPI's exception handlers are
app-scoped, so the context that owns one maps it for the whole application
and a second registration here would be the duplicate
docs/reference/patterns.md warns against. That this context relies on
registrations it does not make is not something the source can state, so
the contract tier walks both.

Four classes on the 400 line where the sibling contexts have one or two,
and the count is what a standing authorization costs. Every one of them
guards a field stated on behalf of a machine, so each refusal has to name
which field rather than saying the request was malformed.
"""

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from keeper.pursuit.aggregates.pursuit import (
    InvalidPursuitBeamlineError,
    InvalidPursuitBudgetError,
    InvalidPursuitChargeError,
    InvalidPursuitGoalError,
    InvalidPursuitScopesError,
    PursuitAlreadyExistsError,
    PursuitCannotBeResumedError,
    PursuitCannotBeWithdrawnError,
    PursuitNotFoundError,
    PursuitRoundCannotBeClosedError,
    PursuitRoundCannotBeOpenedError,
)
from keeper.pursuit.features import (
    charge_pursuit,
    close_pursuit_round,
    get_pursuit,
    list_pursuits,
    open_pursuit_round,
    resume_pursuit,
    start_pursuit,
    withdraw_pursuit,
)


async def _handle_bad_request(request: Request, exc: Exception) -> JSONResponse:
    """The caller sent something this context can see is wrong."""
    _ = request
    return JSONResponse(status_code=status.HTTP_400_BAD_REQUEST, content={"detail": str(exc)})


async def _handle_not_found(request: Request, exc: Exception) -> JSONResponse:
    """The id names nothing this system has a record of."""
    _ = request
    return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"detail": str(exc)})


async def _handle_conflict(request: Request, exc: Exception) -> JSONResponse:
    """The request disagrees with state that is already there."""
    _ = request
    return JSONResponse(status_code=status.HTTP_409_CONFLICT, content={"detail": str(exc)})


def register_pursuit_routes(app: FastAPI) -> None:
    """Include every Pursuit router and register its exception handlers."""
    app.include_router(start_pursuit.router)
    app.include_router(open_pursuit_round.router)
    app.include_router(close_pursuit_round.router)
    app.include_router(charge_pursuit.router)
    app.include_router(resume_pursuit.router)
    app.include_router(withdraw_pursuit.router)
    app.include_router(get_pursuit.router)
    app.include_router(list_pursuits.router)

    for bad_request_cls in (
        InvalidPursuitGoalError,
        InvalidPursuitBeamlineError,
        InvalidPursuitScopesError,
        InvalidPursuitBudgetError,
        InvalidPursuitChargeError,
    ):
        app.add_exception_handler(bad_request_cls, _handle_bad_request)
    app.add_exception_handler(PursuitNotFoundError, _handle_not_found)
    for conflict_cls in (
        PursuitAlreadyExistsError,
        PursuitCannotBeWithdrawnError,
        PursuitRoundCannotBeOpenedError,
        PursuitRoundCannotBeClosedError,
        PursuitCannotBeResumedError,
    ):
        app.add_exception_handler(conflict_cls, _handle_conflict)


__all__ = ["register_pursuit_routes"]
