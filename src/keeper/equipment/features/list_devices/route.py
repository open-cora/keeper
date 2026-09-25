"""HTTP door for listing devices.

`GET /devices`, newest first, filterable by the control system's address
and by disposition, paged with an opaque cursor.

A collection on the same path the registering endpoint posts to, rather
than a route of its own such as `/devices/by-address/{scheme}/{value}`.
Two reasons. An address is free text in the general case, and a path
segment is the one place that has to be escaped by hand, which for an
address ending in a punctuation character is not hypothetical; and the
same filter shape grows to answer a second question without a second
endpoint, which `status` already is.

The reference pair is nested in a row and flat in the filter. That is a
fact about query strings rather than a second shape for the pair: a
query string cannot nest.
"""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status
from pydantic import BaseModel, Field

from keeper.equipment.aggregates.device import DeviceStatus
from keeper.equipment.features.list_devices.handler import Handler
from keeper.equipment.features.list_devices.query import (
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    ListDevices,
)
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


class DeviceSummaryResponse(BaseModel):
    """One device, as a list shows it.

    Every field the single read has, plus the two timestamps, because a
    device holds nothing unbounded and there is nothing a page would be
    better off dropping. A caller that finds what it wanted here needs no
    second call.
    """

    device_id: UUID
    external_ref: ExternalRefResponse
    name: str
    status: DeviceStatus = Field(
        description=(
            "What this system has been told. Available means no fault has been "
            "reported and none stands, which is not the same as the device working."
        )
    )
    registered_at: datetime
    updated_at: datetime


class ListDevicesResponse(BaseModel):
    """One page of devices, and how to ask for the next.

    `next_cursor` is null on the last page.
    """

    items: list[DeviceSummaryResponse]
    next_cursor: str | None


def _get_handler(request: Request) -> Handler:
    handler: Handler = request.app.state.equipment.list_devices
    return handler


router = APIRouter(tags=["equipment"])


@router.get(
    "/devices",
    response_model=ListDevicesResponse,
    responses={
        status.HTTP_400_BAD_REQUEST: {
            "model": ErrorResponse,
            "description": (
                "Half an external reference was given, or the cursor did not come "
                "from a previous response."
            ),
        },
        status.HTTP_403_FORBIDDEN: {
            "model": ErrorResponse,
            "description": "The calling principal may not read devices.",
        },
    },
    summary="List devices",
)
async def list_devices(
    handler: Annotated[Handler, Depends(_get_handler)],
    cid: Annotated[UUID, Depends(get_correlation_id)],
    principal_id: Annotated[UUID, Depends(get_principal_id)],
    surface_id: Annotated[UUID, Depends(get_surface_id)],
    external_ref_scheme: Annotated[str | None, Query()] = None,
    external_ref_value: Annotated[str | None, Query()] = None,
    device_status: Annotated[DeviceStatus | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
    cursor: Annotated[str | None, Query()] = None,
) -> ListDevicesResponse:
    page = await handler(
        ListDevices.with_external_ref(
            scheme=external_ref_scheme,
            value=external_ref_value,
            status=device_status,
            limit=limit,
            cursor=cursor,
        ),
        principal_id=principal_id,
        correlation_id=cid,
        surface_id=surface_id,
    )
    return ListDevicesResponse(
        items=[
            DeviceSummaryResponse(
                device_id=summary.device_id,
                external_ref=ExternalRefResponse(
                    scheme=summary.external_ref.scheme,
                    value=summary.external_ref.value,
                ),
                name=summary.name,
                status=summary.status,
                registered_at=summary.registered_at,
                updated_at=summary.updated_at,
            )
            for summary in page.items
        ],
        next_cursor=page.next_cursor,
    )
