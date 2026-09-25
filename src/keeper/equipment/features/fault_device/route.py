"""HTTP door for recording that a device faulted.

`POST /devices/{device_id}/fault`, optionally carrying when.

A verb in the path rather than `PATCH /devices/{device_id}` with a
status field. The two are not equivalent: a PATCH says what the device
should look like afterwards and invites a caller to set the status at
will, while this endpoint names one transition the domain either allows
or refuses. The status is derived from the stream in any case, so there
is nothing for a PATCH to write.

The body carries no severity and no reason. See the command for why
neither belongs on the record.
"""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel

from keeper.equipment.features.fault_device.command import FaultDevice
from keeper.equipment.features.fault_device.handler import Handler
from keeper.infrastructure.request import (
    ErrorResponse,
    get_correlation_id,
    get_principal_id,
    get_surface_id,
)


class FaultDeviceRequest(BaseModel):
    """When it happened, if the caller knows.

    Omitting `occurred_at` means the event is stamped with the moment
    the report arrived, which is the honest answer to a caller saying
    nothing about when.
    """

    occurred_at: datetime | None = None


def _get_handler(request: Request) -> Handler:
    handler: Handler = request.app.state.equipment.fault_device
    return handler


router = APIRouter(tags=["equipment"])


@router.post(
    "/devices/{device_id}/fault",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        status.HTTP_400_BAD_REQUEST: {
            "model": ErrorResponse,
            "description": "The reported timestamp carried no timezone.",
        },
        status.HTTP_403_FORBIDDEN: {
            "model": ErrorResponse,
            "description": "The calling principal may not fault devices.",
        },
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponse,
            "description": "No device has that id.",
        },
        status.HTTP_409_CONFLICT: {
            "model": ErrorResponse,
            "description": "The device is already faulted, or has been retired.",
        },
    },
    summary="Record that a device faulted",
)
async def post_device_fault(
    device_id: UUID,
    body: FaultDeviceRequest,
    handler: Annotated[Handler, Depends(_get_handler)],
    cid: Annotated[UUID, Depends(get_correlation_id)],
    principal_id: Annotated[UUID, Depends(get_principal_id)],
    surface_id: Annotated[UUID, Depends(get_surface_id)],
) -> None:
    await handler(
        FaultDevice(device_id=device_id, occurred_at=body.occurred_at),
        principal_id=principal_id,
        correlation_id=cid,
        surface_id=surface_id,
    )
