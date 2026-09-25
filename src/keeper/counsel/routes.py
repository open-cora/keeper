"""Mount the Counsel HTTP routes, and map its errors onto status codes.

The handler raises typed errors and knows nothing about HTTP. The
translation lives here, in one place, so the same handler can serve the
MCP surface where those numbers mean nothing.

Four shapes, and which ones are absent matters as much as which are
here:

    400  InvalidProposalParametersError
             the values do not satisfy the plan's schema

    403  UnauthorizedError
             the caller is known and refused, which is a different fact
             from 401, where we do not know who is asking

    404  ProposalNotFoundError
             the id names no proposal this system has a record of

    409  ProposalAlreadyExistsError
             a genesis event was asked for on a live stream
         ProposalCannotBeTakenError
             it already has a run, or the run ran a different plan

Four are absent and all four belong to somebody else.
`PlanNotFoundError`, `ExecutionNotFoundError` and
`ExecutionStepNotFoundError` are Execution's, raised by this context's
handlers and mapped by Execution's registration.
`InvalidOccurredAtError` is the shared timestamp helper's, and is also
mapped by Execution, which is the context that first needed it.

FastAPI's exception handlers are app-scoped, so the context that owns
each one maps it for the whole application and a second registration
here would be the duplicate docs/reference/patterns.md warns against.
That this context relies on three registrations it does not make is not
something the source can state, so the contract tier executions them over a
Counsel route.
"""

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from keeper.counsel.aggregates.proposal import (
    InvalidProposalParametersError,
    ProposalAlreadyExistsError,
    ProposalCannotBeTakenError,
    ProposalNotFoundError,
)
from keeper.counsel.errors import UnauthorizedError
from keeper.counsel.features import (
    get_proposal,
    list_proposals,
    make_proposal,
    take_proposal,
)


async def _handle_bad_request(request: Request, exc: Exception) -> JSONResponse:
    """The caller sent something this context can see is wrong."""
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


def register_counsel_routes(app: FastAPI) -> None:
    """Include every Counsel router and register its exception handlers."""
    app.include_router(make_proposal.router)
    app.include_router(get_proposal.router)
    app.include_router(take_proposal.router)
    app.include_router(list_proposals.router)

    app.add_exception_handler(InvalidProposalParametersError, _handle_bad_request)
    app.add_exception_handler(UnauthorizedError, _handle_unauthorized)
    app.add_exception_handler(ProposalNotFoundError, _handle_not_found)
    for conflict_cls in (ProposalAlreadyExistsError, ProposalCannotBeTakenError):
        app.add_exception_handler(conflict_cls, _handle_conflict)


__all__ = ["register_counsel_routes"]
