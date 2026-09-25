"""Mount the Equipment HTTP routes, and map its errors onto status codes.

The handler raises typed errors and knows nothing about HTTP. The
translation lives here, in one place, so the same handler can serve the
MCP surface where those numbers mean nothing.

Four shapes:

    400  InvalidDeviceNameError
             the label is empty, whitespace-only, or too long
         InvalidDeviceFilterError
             a list was asked for half an external reference

    403  UnauthorizedError
             the caller is known and refused, which is a different fact
             from 401, where we do not know who is asking

    404  DeviceNotFoundError
             the id names no device this system has a record of

    409  DeviceAlreadyExistsError
             a genesis event was asked for on a live stream
         DeviceCannotBeFaultedError
         DeviceCannotBeRecoveredError
         DeviceCannotBeRetiredError
             the transition disagrees with the state the stream is in

Three refusal classes rather than one, where the sibling context to this
one uses a single class with a discriminator. The rule that decides it
is R6 in docs/reference/naming.md: one class per VERB, with the
discriminating state carried on the error. Counsel has one verb refused
two ways and so has one class; this has three verbs, so it has three.
Each carries the device's status, which is the fact the caller did not
have.

`InvalidOccurredAtError` is absent and belongs to somebody else. It is
the shared timestamp helper's, raised by two of this context's commands
and mapped by Execution, which is the context that first needed it.
FastAPI's exception handlers are app-scoped, so the context that owns
each one maps it for the whole application and a second registration
here would be the duplicate docs/reference/patterns.md warns against.
That this context relies on a registration it does not make is not
something the source can state, so the contract tier executions it over an
Equipment route.
"""

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from keeper.equipment.aggregates.device import (
    DeviceAlreadyExistsError,
    DeviceCannotBeFaultedError,
    DeviceCannotBeRecoveredError,
    DeviceCannotBeRetiredError,
    DeviceNotFoundError,
    InvalidDeviceFilterError,
    InvalidDeviceNameError,
)
from keeper.equipment.errors import UnauthorizedError
from keeper.equipment.features import (
    fault_device,
    get_device,
    list_devices,
    recover_device,
    register_device,
    retire_device,
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


def register_equipment_routes(app: FastAPI) -> None:
    """Include every Equipment router and register its exception handlers."""
    app.include_router(register_device.router)
    app.include_router(fault_device.router)
    app.include_router(recover_device.router)
    app.include_router(retire_device.router)
    app.include_router(get_device.router)
    app.include_router(list_devices.router)

    for bad_request_cls in (InvalidDeviceNameError, InvalidDeviceFilterError):
        app.add_exception_handler(bad_request_cls, _handle_bad_request)
    app.add_exception_handler(UnauthorizedError, _handle_unauthorized)
    app.add_exception_handler(DeviceNotFoundError, _handle_not_found)
    for conflict_cls in (
        DeviceAlreadyExistsError,
        DeviceCannotBeFaultedError,
        DeviceCannotBeRecoveredError,
        DeviceCannotBeRetiredError,
    ):
        app.add_exception_handler(conflict_cls, _handle_conflict)


__all__ = ["register_equipment_routes"]
