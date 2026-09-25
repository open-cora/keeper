"""Mount the Custody HTTP routes, and map its errors onto status codes.

The handler raises typed errors and knows nothing about HTTP. The
translation lives here, in one place, so the same handler can serve the
MCP surface where those numbers mean nothing.

Three shapes, and the interesting part is which ones are absent:

    403  UnauthorizedError
             the caller is known and refused, which is a different fact
             from 401, where we do not know who is asking

    404  DatasetNotFoundError
             the id names no dataset this system has a record of

    409  DatasetAlreadyExistsError
             a genesis event was asked for on a live stream

**There is no 400 group, and that is the model rather than an omission.**
This context holds a reference to something it cannot read, so it has
nothing of its own to declare malformed. The two malformed-input shapes
that can arise here are both raised by shared code this context borrows:
`InvalidIdentifierError` from the shared value object, and
`InvalidOccurredAtError` from the shared timestamp helper. Both are
registered by the context that first needed them, which is Execution for
each, FastAPI's exception handlers are app-scoped, and both already
answer 400. Registering them again here is the duplicate
docs/reference/patterns.md warns against, so it is not done.

`InvalidCursorError` is absent too, and is the third kind: a cross-BC
infrastructure error registered once at the composition root rather than
by any context.

`ExecutionNotFoundError` and `ExecutionStepNotFoundError` are absent for
the same reason as the first two, and they are the ones most likely to be
reached for: `register_dataset` raises both, and both map to 404 through
Execution's registration rather than through anything here. The rule is
that a cross-BC domain error is registered only by the context that owns
the aggregate it belongs to.
"""

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from keeper.custody.aggregates.dataset import (
    DatasetAlreadyExistsError,
    DatasetNotFoundError,
)
from keeper.custody.errors import UnauthorizedError
from keeper.custody.features import get_dataset, list_datasets, register_dataset


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


def register_custody_routes(app: FastAPI) -> None:
    """Include every Custody router and register its exception handlers."""
    app.include_router(register_dataset.router)
    app.include_router(get_dataset.router)
    app.include_router(list_datasets.router)

    app.add_exception_handler(UnauthorizedError, _handle_unauthorized)
    app.add_exception_handler(DatasetNotFoundError, _handle_not_found)
    app.add_exception_handler(DatasetAlreadyExistsError, _handle_conflict)


__all__ = ["register_custody_routes"]
