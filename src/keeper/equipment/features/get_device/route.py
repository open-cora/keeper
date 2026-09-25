"""HTTP door for reading one device.

`GET /devices/{device_id}`.

`external_ref` is nested rather than flattened into two top-level keys,
matching the shape the registering endpoint accepts. A caller that reads
a device and registers another should not meet two spellings of one
pair.

`status` is the derived value, rendered as the word the enum carries. It
says what this system has been told, and the response says so in the
field's description rather than leaving a reader to assume the stronger
claim.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel, Field

from keeper.equipment.aggregates.device import DeviceStatus
from keeper.equipment.features.get_device.handler import Handler
from keeper.equipment.features.get_device.query import GetDevice
from keeper.infrastructure.request import (
    ErrorResponse,
    get_correlation_id,
    get_principal_id,
    get_surface_id,
)


class ExternalRefResponse(BaseModel):
    """Where the control system publishes this device."""

    scheme: str
    value: str


class DeviceResponse(BaseModel):
    """One device, as this system holds it."""

    device_id: UUID
    external_ref: ExternalRefResponse
    name: str
    status: DeviceStatus = Field(
        description=(
            "What this system has been told. Available means no fault has been "
            "reported and none stands, which is not the same as the device working."
        )
    )


def _get_handler(request: Request) -> Handler:
    handler: Handler = request.app.state.equipment.get_device
    return handler


router = APIRouter(tags=["equipment"])


@router.get(
    "/devices/{device_id}",
    response_model=DeviceResponse,
    responses={
        status.HTTP_403_FORBIDDEN: {
            "model": ErrorResponse,
            "description": "The calling principal may not read devices.",
        },
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponse,
            "description": "No device has that id.",
        },
    },
    summary="Read a device",
)
async def get_device(
    device_id: UUID,
    handler: Annotated[Handler, Depends(_get_handler)],
    cid: Annotated[UUID, Depends(get_correlation_id)],
    principal_id: Annotated[UUID, Depends(get_principal_id)],
    surface_id: Annotated[UUID, Depends(get_surface_id)],
) -> DeviceResponse:
    device = await handler(
        GetDevice(device_id=device_id),
        principal_id=principal_id,
        correlation_id=cid,
        surface_id=surface_id,
    )
    return DeviceResponse(
        device_id=device.id,
        external_ref=ExternalRefResponse(
            scheme=device.external_ref.scheme, value=device.external_ref.value
        ),
        name=device.name.value,
        status=device.status,
    )
