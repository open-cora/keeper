"""Mount the Authority HTTP routes, and map its errors onto status codes.

The handler raises typed errors and knows nothing about HTTP. The
translation lives here, in one place, so the same handler can serve the
MCP surface where those numbers mean nothing.

Five shapes:

    403  UnauthorizedError
             the caller is known and refused, which is a different fact
             from 401, where we do not know who is asking

    404  PolicyNotFoundError
             the id names no policy this system has a record of

    409  PolicyAlreadyExistsError
             a genesis event was asked for on a live stream
         PolicyCannotGrantPermissionError
             the permission is already held
         PolicyCannotRevokePermissionError
             the permission is not held

    422  PolicyWouldBeUngovernableError
             the policy would be left with nobody able to change it
         SystemPrincipalCannotBeGrantedError
             the grantee is the unauthenticated fallback identity

         Both are refusals of the SHAPE asked for rather than conflicts
         with what is stored, which is what separates them from the 409s.

The idempotency and concurrency shapes are NOT registered here. They are
raised by machinery every context shares, so they are mapped once at the
composition root rather than by whichever context happens to be mounted.
"""

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from keeper.authority.aggregates.policy import (
    PolicyAlreadyExistsError,
    PolicyCannotGrantPermissionError,
    PolicyCannotRevokePermissionError,
    PolicyNotFoundError,
    PolicyWouldBeUngovernableError,
    SystemPrincipalCannotBeGrantedError,
)
from keeper.authority.errors import UnauthorizedError
from keeper.authority.features import (
    define_policy,
    get_policy,
    grant_permission,
    revoke_permission,
)


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


async def _handle_unprocessable(request: Request, exc: Exception) -> JSONResponse:
    """The request is well formed and asks for something a policy may not be.

    Not a 409. Nothing about the stored policy conflicts with this: the
    same request would be refused against an empty system. The rulebook
    itself forbids the shape being asked for.
    """
    _ = request
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, content={"detail": str(exc)}
    )


def register_authority_routes(app: FastAPI) -> None:
    """Include every Authority router and register its exception handlers."""
    app.include_router(define_policy.router)
    app.include_router(grant_permission.router)
    app.include_router(revoke_permission.router)
    app.include_router(get_policy.router)

    app.add_exception_handler(PolicyNotFoundError, _handle_not_found)
    app.add_exception_handler(UnauthorizedError, _handle_unauthorized)
    app.add_exception_handler(PolicyAlreadyExistsError, _handle_conflict)
    app.add_exception_handler(PolicyCannotGrantPermissionError, _handle_conflict)
    app.add_exception_handler(PolicyCannotRevokePermissionError, _handle_conflict)
    app.add_exception_handler(PolicyWouldBeUngovernableError, _handle_unprocessable)
    app.add_exception_handler(SystemPrincipalCannotBeGrantedError, _handle_unprocessable)


__all__ = ["register_authority_routes"]
