"""MCP door for retiring a device.

The same handler the HTTP route uses, fetched per call so it sees the
bundle the lifespan wired rather than whatever existed at registration.

No idempotency key. MCP has no client-supplied retry tag to carry one,
and a replayed call is refused by the domain in any case.
"""

from collections.abc import Callable
from typing import Any
from uuid import UUID

from mcp.server.fastmcp import Context, FastMCP
from pydantic import BaseModel

from keeper.equipment.features.retire_device.command import RetireDevice
from keeper.equipment.features.retire_device.handler import Handler
from keeper.infrastructure.observability import current_correlation_id
from keeper.infrastructure.request import get_mcp_surface_id
from keeper.infrastructure.slices.principal import get_mcp_principal_id


class RetireDeviceOutput(BaseModel):
    """What the tool hands back.

    The id it was given, because a tool result of nothing reads as a
    failure to a caller that cannot see a 204.
    """

    device_id: UUID


def register(mcp: FastMCP, *, get_handler: Callable[[], Handler]) -> None:
    """Register the tool on the given MCP server."""

    @mcp.tool(
        name="retire_device",
        description=(
            "Stop counting a device: it is no longer one this system treats as "
            "present. The record and its history stay readable. Refused if the "
            "device is already retired."
        ),
    )
    async def retire_device_tool(  # pyright: ignore[reportUnusedFunction]
        ctx: Context[Any, Any, Any],
        device_id: UUID,
    ) -> RetireDeviceOutput:
        handler = get_handler()
        await handler(
            RetireDevice(device_id=device_id),
            principal_id=get_mcp_principal_id(ctx),
            # The tool runs inside the instrumented request that carried
            # it, so the trace context is already in scope.
            correlation_id=current_correlation_id(),
            surface_id=get_mcp_surface_id(),
        )
        return RetireDeviceOutput(device_id=device_id)
