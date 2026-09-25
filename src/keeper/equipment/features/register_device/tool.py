"""MCP door for registering a device.

The same handler the HTTP route uses, fetched per call so it sees the
bundle the lifespan wired rather than whatever existed at registration.

The reference pair arrives as two flat arguments here, where the route
takes a nested object. A tool's arguments are a flat keyword list, and
nesting one object inside it would buy shape at the cost of every client
having to construct it. Both doors build the same value object before the
command exists, which is where the shape actually matters.

No idempotency key. MCP has no client-supplied retry tag to carry one, so
the wrapped handler is called with None and behaves as the bare one.
"""

from collections.abc import Callable
from typing import Any
from uuid import UUID

from mcp.server.fastmcp import Context, FastMCP
from pydantic import BaseModel

from keeper.equipment.aggregates.device import DeviceName
from keeper.equipment.features.register_device.command import RegisterDevice
from keeper.equipment.features.register_device.handler import IdempotentHandler
from keeper.infrastructure.observability import current_correlation_id
from keeper.infrastructure.request import get_mcp_surface_id
from keeper.infrastructure.slices.principal import get_mcp_principal_id
from keeper.shared.identifier import Identifier


class RegisterDeviceOutput(BaseModel):
    """What the tool hands back."""

    device_id: UUID


def register(mcp: FastMCP, *, get_handler: Callable[[], IdempotentHandler]) -> None:
    """Register the tool on the given MCP server."""

    @mcp.tool(
        name="register_device",
        description=(
            "Enrol a piece of hardware: the address its control system publishes "
            "it at, and a short label for it. The label is this system's own, so "
            "do not copy the facility's description field into it."
        ),
    )
    async def register_device_tool(  # pyright: ignore[reportUnusedFunction]
        ctx: Context[Any, Any, Any],
        external_ref_scheme: str,
        external_ref_value: str,
        name: str,
    ) -> RegisterDeviceOutput:
        handler = get_handler()
        device_id = await handler(
            RegisterDevice(
                external_ref=Identifier(scheme=external_ref_scheme, value=external_ref_value),
                name=DeviceName(name),
            ),
            principal_id=get_mcp_principal_id(ctx),
            # The tool runs inside the instrumented request that carried
            # it, so the trace context is already in scope.
            correlation_id=current_correlation_id(),
            surface_id=get_mcp_surface_id(),
        )
        return RegisterDeviceOutput(device_id=device_id)
