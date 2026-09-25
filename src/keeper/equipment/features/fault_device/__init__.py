"""The fault_device slice, re-exported so callers read `.bind`."""

from keeper.equipment.features.fault_device.command import FaultDevice
from keeper.equipment.features.fault_device.decider import decide
from keeper.equipment.features.fault_device.handler import Handler, bind
from keeper.equipment.features.fault_device.route import router

__all__ = ["FaultDevice", "Handler", "bind", "decide", "router"]
