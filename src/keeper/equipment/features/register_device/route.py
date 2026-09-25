"""HTTP door for registering a device.

`POST /devices`, carrying the address the control system publishes the
hardware at and this system's label for it.

A POST that creates a record of something that already exists at a
beamline, not a POST that installs anything. The resource being created
is the record. Nothing here reaches the control system, and nothing here
could: a caller that can see the device is the one that knows its
address.

`external_ref` is nested rather than flattened into two top-level keys,
so the body cannot express half a reference and the shape matches the
value object it becomes. The bounds on its strings and on the label are
declared here as well as on the value objects: this one turns an
over-long label into FastAPI's standard 422 before a command exists, and
the value object is what holds for the MCP surface and for any caller
that reaches the decider another way.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request, status
from pydantic import BaseModel, Field

from keeper.equipment.aggregates.device import DEVICE_NAME_MAX_LENGTH, DeviceName
from keeper.equipment.features.register_device.command import RegisterDevice
from keeper.equipment.features.register_device.handler import IdempotentHandler
from keeper.infrastructure.request import (
    ErrorResponse,
    get_correlation_id,
    get_principal_id,
    get_surface_id,
)
from keeper.shared.identifier import (
    IDENTIFIER_SCHEME_MAX_LENGTH,
    IDENTIFIER_VALUE_MAX_LENGTH,
    Identifier,
)


class ExternalRefBody(BaseModel):
    """Where the control system publishes this device.

    `scheme` names the addressing vocabulary. It is open on purpose:
    which control system a deployment runs is a deployment's fact, not
    something this system should hold a list of.

    `value` is stored exactly as it arrives, trimmed and no more. A
    control system whose address can be spelled two ways will make two
    records unless the caller settles on one first.
    """

    scheme: str = Field(min_length=1, max_length=IDENTIFIER_SCHEME_MAX_LENGTH)
    value: str = Field(min_length=1, max_length=IDENTIFIER_VALUE_MAX_LENGTH)


class RegisterDeviceRequest(BaseModel):
    """The device to write down.

    `name` is this system's label and not the facility's own description
    field. An adapter that copies that field in is putting whatever
    somebody typed at a beamline into a table that cannot be edited.
    """

    external_ref: ExternalRefBody
    name: str = Field(min_length=1, max_length=DEVICE_NAME_MAX_LENGTH)


class RegisterDeviceResponse(BaseModel):
    """The id of the device record that was created."""

    device_id: UUID


def _get_handler(request: Request) -> IdempotentHandler:
    handler: IdempotentHandler = request.app.state.equipment.register_device
    return handler


router = APIRouter(tags=["equipment"])


@router.post(
    "/devices",
    status_code=status.HTTP_201_CREATED,
    response_model=RegisterDeviceResponse,
    responses={
        status.HTTP_400_BAD_REQUEST: {
            "model": ErrorResponse,
            "description": "The external reference or the label is not well-formed.",
        },
        status.HTTP_403_FORBIDDEN: {
            "model": ErrorResponse,
            "description": "The calling principal may not register devices.",
        },
    },
    summary="Register a device",
)
async def post_devices(
    body: RegisterDeviceRequest,
    handler: Annotated[IdempotentHandler, Depends(_get_handler)],
    cid: Annotated[UUID, Depends(get_correlation_id)],
    principal_id: Annotated[UUID, Depends(get_principal_id)],
    surface_id: Annotated[UUID, Depends(get_surface_id)],
    idempotency_key: Annotated[
        str | None,
        Header(
            alias="Idempotency-Key",
            description="Replay the same key to get the same device back, not a second one.",
        ),
    ] = None,
) -> RegisterDeviceResponse:
    device_id = await handler(
        RegisterDevice(
            external_ref=Identifier(scheme=body.external_ref.scheme, value=body.external_ref.value),
            name=DeviceName(body.name),
        ),
        principal_id=principal_id,
        correlation_id=cid,
        surface_id=surface_id,
        idempotency_key=idempotency_key,
    )
    return RegisterDeviceResponse(device_id=device_id)
