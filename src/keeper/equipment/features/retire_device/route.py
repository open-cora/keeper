"""HTTP door for retiring a device.

`POST /devices/{device_id}/retire`, carrying nothing.

An empty body, because there is nothing to say. The two reported
transitions take an optional time; this one is an act performed here, so
the moment is this system's clock and there is no field a caller could
fill.

A verb in the path rather than `DELETE /devices/{device_id}`. A DELETE
says the record is gone, and it is not: the stream stays and the history
stays readable. What changes is that the register no longer counts the
device.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status

from keeper.equipment.features.retire_device.command import RetireDevice
from keeper.equipment.features.retire_device.handler import Handler
from keeper.infrastructure.request import (
    ErrorResponse,
    get_correlation_id,
    get_principal_id,
    get_surface_id,
)


def _get_handler(request: Request) -> Handler:
    handler: Handler = request.app.state.equipment.retire_device
    return handler


router = APIRouter(tags=["equipment"])


@router.post(
    "/devices/{device_id}/retire",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        status.HTTP_403_FORBIDDEN: {
            "model": ErrorResponse,
            "description": "The calling principal may not retire devices.",
        },
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponse,
            "description": "No device has that id.",
        },
        status.HTTP_409_CONFLICT: {
            "model": ErrorResponse,
            "description": "The device is already retired.",
        },
    },
    summary="Retire a device",
)
async def post_device_retire(
    device_id: UUID,
    handler: Annotated[Handler, Depends(_get_handler)],
    cid: Annotated[UUID, Depends(get_correlation_id)],
    principal_id: Annotated[UUID, Depends(get_principal_id)],
    surface_id: Annotated[UUID, Depends(get_surface_id)],
) -> None:
    await handler(
        RetireDevice(device_id=device_id),
        principal_id=principal_id,
        correlation_id=cid,
        surface_id=surface_id,
    )
