"""MCP door for recording a device recover.

The same handler the HTTP route uses, fetched per call so it sees the
bundle the lifespan wired rather than whatever existed at registration.

No idempotency key. MCP has no client-supplied retry tag to carry one,
and a replayed call is refused by the domain in any case.
"""

from collections.abc import Callable
from datetime import datetime
from typing import Any
from uuid import UUID

from mcp.server.fastmcp import Context, FastMCP
from pydantic import BaseModel

from keeper.equipment.features.recover_device.command import RecoverDevice
from keeper.equipment.features.recover_device.handler import Handler
from keeper.infrastructure.observability import current_correlation_id
from keeper.infrastructure.request import get_mcp_surface_id
from keeper.infrastructure.slices.principal import get_mcp_principal_id


class RecoverDeviceOutput(BaseModel):
    """What the tool hands back.

    The id it was given, because a tool result of nothing reads as a
    failure to a caller that cannot see a 204.
    """

    device_id: UUID


def register(mcp: FastMCP, *, get_handler: Callable[[], Handler]) -> None:
    """Register the tool on the given MCP server."""

    @mcp.tool(
        name="recover_device",
        description=(
            "Record that a device came back from a fault. Refused if the device is "
            "not currently faulted, which usually means the fault was never reported."
        ),
    )
    async def recover_device_tool(  # pyright: ignore[reportUnusedFunction]
        ctx: Context[Any, Any, Any],
        device_id: UUID,
        occurred_at: datetime | None = None,
    ) -> RecoverDeviceOutput:
        handler = get_handler()
        await handler(
            RecoverDevice(device_id=device_id, occurred_at=occurred_at),
            principal_id=get_mcp_principal_id(ctx),
            # The tool runs inside the instrumented request that carried
            # it, so the trace context is already in scope.
            correlation_id=current_correlation_id(),
            surface_id=get_mcp_surface_id(),
        )
        return RecoverDeviceOutput(device_id=device_id)
