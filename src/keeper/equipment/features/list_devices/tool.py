"""MCP door for listing devices.

The same handler the HTTP route uses, fetched per call so it sees the
bundle the lifespan wired rather than whatever existed at registration.

This is the tool an adapter reaches for first. It holds the address its
control system publishes a device at and no id, because ids are minted
here, so resolving one to the other is what every fault it later reports
depends on.
"""

from collections.abc import Callable
from datetime import datetime
from typing import Any
from uuid import UUID

from mcp.server.fastmcp import Context, FastMCP
from pydantic import BaseModel, Field

from keeper.equipment.aggregates.device import DeviceStatus
from keeper.equipment.features.list_devices.handler import Handler
from keeper.equipment.features.list_devices.query import DEFAULT_PAGE_SIZE, ListDevices
from keeper.infrastructure.observability import current_correlation_id
from keeper.infrastructure.request import get_mcp_surface_id
from keeper.infrastructure.slices.principal import get_mcp_principal_id


class DeviceSummaryItem(BaseModel):
    """One device, as a list shows it."""

    device_id: UUID
    external_ref_scheme: str
    external_ref_value: str
    name: str
    status: DeviceStatus
    registered_at: datetime
    updated_at: datetime


class ListDevicesOutput(BaseModel):
    """One page of devices, and how to ask for the next."""

    items: list[DeviceSummaryItem]
    next_cursor: str | None = Field(
        default=None, description="Pass back as `cursor` for the next page. Null on the last."
    )


def register(mcp: FastMCP, *, get_handler: Callable[[], Handler]) -> None:
    """Register the tool on the given MCP server."""

    @mcp.tool(
        name="list_devices",
        description=(
            "List devices, newest first. Filter by the control system's address to "
            "resolve one to its id before reporting anything about it, or by status "
            "to see what is currently faulted. More than one device may carry the "
            "same address; nothing prevents it."
        ),
    )
    async def list_devices_tool(  # pyright: ignore[reportUnusedFunction]
        ctx: Context[Any, Any, Any],
        external_ref_scheme: str | None = None,
        external_ref_value: str | None = None,
        status: DeviceStatus | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
        cursor: str | None = None,
    ) -> ListDevicesOutput:
        handler = get_handler()
        page = await handler(
            ListDevices.with_external_ref(
                scheme=external_ref_scheme,
                value=external_ref_value,
                status=status,
                limit=limit,
                cursor=cursor,
            ),
            principal_id=get_mcp_principal_id(ctx),
            # The tool runs inside the instrumented request that carried
            # it, so the trace context is already in scope.
            correlation_id=current_correlation_id(),
            surface_id=get_mcp_surface_id(),
        )
        return ListDevicesOutput(
            items=[
                DeviceSummaryItem(
                    device_id=summary.device_id,
                    external_ref_scheme=summary.external_ref.scheme,
                    external_ref_value=summary.external_ref.value,
                    name=summary.name,
                    status=summary.status,
                    registered_at=summary.registered_at,
                    updated_at=summary.updated_at,
                )
                for summary in page.items
            ],
            next_cursor=page.next_cursor,
        )
