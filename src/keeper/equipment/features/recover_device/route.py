"""HTTP door for recording that a device recovered.

`POST /devices/{device_id}/recover`, optionally carrying when.

A verb in the path, for the reason its partner endpoint gives: this
names one transition the domain either allows or refuses, where a PATCH
would invite a caller to set the status directly.
"""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel

from keeper.equipment.features.recover_device.command import RecoverDevice
from keeper.equipment.features.recover_device.handler import Handler
from keeper.infrastructure.request import (
    ErrorResponse,
    get_correlation_id,
    get_principal_id,
    get_surface_id,
)


class RecoverDeviceRequest(BaseModel):
    """When it happened, if the caller knows.

    Omitting `occurred_at` means the event is stamped with the moment
    the report arrived, which is the honest answer to a caller saying
    nothing about when.
    """

    occurred_at: datetime | None = None


def _get_handler(request: Request) -> Handler:
    handler: Handler = request.app.state.equipment.recover_device
    return handler


router = APIRouter(tags=["equipment"])


@router.post(
    "/devices/{device_id}/recover",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        status.HTTP_400_BAD_REQUEST: {
            "model": ErrorResponse,
            "description": "The reported timestamp carried no timezone.",
        },
        status.HTTP_403_FORBIDDEN: {
            "model": ErrorResponse,
            "description": "The calling principal may not recover devices.",
        },
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponse,
            "description": "No device has that id.",
        },
        status.HTTP_409_CONFLICT: {
            "model": ErrorResponse,
            "description": "The device is not currently faulted.",
        },
    },
    summary="Record that a device recovered",
)
async def post_device_recover(
    device_id: UUID,
    body: RecoverDeviceRequest,
    handler: Annotated[Handler, Depends(_get_handler)],
    cid: Annotated[UUID, Depends(get_correlation_id)],
    principal_id: Annotated[UUID, Depends(get_principal_id)],
    surface_id: Annotated[UUID, Depends(get_surface_id)],
) -> None:
    await handler(
        RecoverDevice(device_id=device_id, occurred_at=body.occurred_at),
        principal_id=principal_id,
        correlation_id=cid,
        surface_id=surface_id,
    )
