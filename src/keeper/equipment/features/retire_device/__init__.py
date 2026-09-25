"""The retire_device slice, re-exported so callers read `.bind`."""

from keeper.equipment.features.retire_device.command import RetireDevice
from keeper.equipment.features.retire_device.decider import decide
from keeper.equipment.features.retire_device.handler import Handler, bind
from keeper.equipment.features.retire_device.route import router

__all__ = ["Handler", "RetireDevice", "bind", "decide", "router"]
