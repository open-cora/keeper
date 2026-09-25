"""Mount the Access HTTP routes, and map its errors onto status codes.

The handler raises typed errors and knows nothing about HTTP. The
translation lives here, in one place, so the same handler can serve the
MCP surface where those numbers mean nothing.

Five shapes, grouped by the answer they produce:

    403  UnauthorizedError
             the caller is known and refused, which is a different fact
             from 401, where we do not know who is asking

    404  ActorNotFoundError
             the id names no actor this system has a record of

    409  ActorAlreadyExistsError
             a genesis event was asked for on a live stream
         ActorCannotBeDeactivatedError
             the actor is there and is already switched off
         ActorCannotBeReactivatedError
             the actor is there and is already switched on

         Three different facts sharing one status. They are separate
         classes because the caller's next move differs: retry, stop,
         or re-read.

The concurrency and idempotency shapes are NOT here. They were, while
Access was the only context using the wrapper, with a note to move them
when a second one needed it. Authority does, so they now live in
`keeper.api.exception_handlers` and are registered once at the
composition root.
"""

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from keeper.access.aggregates.actor import (
    ActorAlreadyExistsError,
    ActorCannotBeDeactivatedError,
    ActorCannotBeReactivatedError,
    ActorNotFoundError,
)
from keeper.access.errors import UnauthorizedError
from keeper.access.features import deactivate_actor, get_actor, reactivate_actor, register_actor


async def _handle_not_found(request: Request, exc: Exception) -> JSONResponse:
    """The id names nothing this system has a record of."""
    _ = request
    return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"detail": str(exc)})


async def _handle_unauthorized(request: Request, exc: Exception) -> JSONResponse:
    """A known caller, refused."""
    _ = request
    return JSONResponse(status_code=status.HTTP_403_FORBIDDEN, content={"detail": str(exc)})


async def _handle_conflict(request: Request, exc: Exception) -> JSONResponse:
    """The request disagrees with state that is already there."""
    _ = request
    return JSONResponse(status_code=status.HTTP_409_CONFLICT, content={"detail": str(exc)})


def register_access_routes(app: FastAPI) -> None:
    """Include every Access router and register its exception handlers."""
    app.include_router(register_actor.router)
    app.include_router(deactivate_actor.router)
    app.include_router(reactivate_actor.router)
    app.include_router(get_actor.router)

    app.add_exception_handler(ActorNotFoundError, _handle_not_found)
    app.add_exception_handler(UnauthorizedError, _handle_unauthorized)
    app.add_exception_handler(ActorAlreadyExistsError, _handle_conflict)
    app.add_exception_handler(ActorCannotBeDeactivatedError, _handle_conflict)
    app.add_exception_handler(ActorCannotBeReactivatedError, _handle_conflict)


__all__ = ["register_access_routes"]
