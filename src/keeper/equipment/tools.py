"""Register the Equipment MCP tools on the shared server.

`get_handlers` is called per tool call, not at registration, so a tool
always reaches the bundle the lifespan wired rather than one captured
before startup finished.

All six are here, which is unlike the sibling contexts, and the reason
is who the caller is. Counsel publishes the three an agent holds and
leaves the rest to Execution's tools. Here the agent and the reporter
are the same kind of client: something watching a beamline, which has to
resolve an address before it can say anything, and then says it. Both
halves of that loop are in this context, so both are on this surface.
"""

from collections.abc import Callable

from mcp.server.fastmcp import FastMCP

from keeper.equipment.features.fault_device import tool as fault_device_tool
from keeper.equipment.features.get_device import tool as get_device_tool
from keeper.equipment.features.list_devices import tool as list_devices_tool
from keeper.equipment.features.recover_device import tool as recover_device_tool
from keeper.equipment.features.register_device import tool as register_device_tool
from keeper.equipment.features.retire_device import tool as retire_device_tool
from keeper.equipment.wire import EquipmentHandlers


def register_equipment_tools(
    mcp: FastMCP,
    *,
    get_handlers: Callable[[], EquipmentHandlers],
) -> None:
    """Register every Equipment slice's MCP tool."""
    register_device_tool.register(
        mcp,
        get_handler=lambda: get_handlers().register_device,
    )
    fault_device_tool.register(
        mcp,
        get_handler=lambda: get_handlers().fault_device,
    )
    recover_device_tool.register(
        mcp,
        get_handler=lambda: get_handlers().recover_device,
    )
    retire_device_tool.register(
        mcp,
        get_handler=lambda: get_handlers().retire_device,
    )
    get_device_tool.register(
        mcp,
        get_handler=lambda: get_handlers().get_device,
    )
    list_devices_tool.register(
        mcp,
        get_handler=lambda: get_handlers().list_devices,
    )


__all__ = ["register_equipment_tools"]
