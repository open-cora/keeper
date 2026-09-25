"""MCP door for reading one device.

The same handler the HTTP route uses, fetched per call so it sees the
bundle the lifespan wired rather than whatever existed at registration.

The reference comes back as two flat fields, matching how the
registering tool accepts it, because a tool's arguments and results are
flat keyword shapes.
"""

from collections.abc import Callable
from typing import Any
from uuid import UUID

from mcp.server.fastmcp import Context, FastMCP
from pydantic import BaseModel, Field

from keeper.equipment.aggregates.device import DeviceStatus
from keeper.equipment.features.get_device.handler import Handler
from keeper.equipment.features.get_device.query import GetDevice
from keeper.infrastructure.observability import current_correlation_id
from keeper.infrastructure.request import get_mcp_surface_id
from keeper.infrastructure.slices.principal import get_mcp_principal_id


class GetDeviceOutput(BaseModel):
    """One device, as this system holds it."""

    device_id: UUID
    external_ref_scheme: str
    external_ref_value: str
    name: str
    status: DeviceStatus = Field(
        description=(
            "What this system has been told. Available means no fault has been "
            "reported and none stands, which is not the same as the device working."
        )
    )


def register(mcp: FastMCP, *, get_handler: Callable[[], Handler]) -> None:
    """Register the tool on the given MCP server."""

    @mcp.tool(
        name="get_device",
        description=(
            "Read one device by its id: where its control system publishes it, "
            "this system's label for it, and what state it was last reported in."
        ),
    )
    async def get_device_tool(  # pyright: ignore[reportUnusedFunction]
        ctx: Context[Any, Any, Any],
        device_id: UUID,
    ) -> GetDeviceOutput:
        handler = get_handler()
        device = await handler(
            GetDevice(device_id=device_id),
            principal_id=get_mcp_principal_id(ctx),
            # The tool runs inside the instrumented request that carried
            # it, so the trace context is already in scope.
            correlation_id=current_correlation_id(),
            surface_id=get_mcp_surface_id(),
        )
        return GetDeviceOutput(
            device_id=device.id,
            external_ref_scheme=device.external_ref.scheme,
            external_ref_value=device.external_ref.value,
            name=device.name.value,
            status=device.status,
        )
