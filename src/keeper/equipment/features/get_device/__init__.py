"""The get_device slice, re-exported so callers read `.bind`."""

from keeper.equipment.features.get_device.handler import Handler, bind
from keeper.equipment.features.get_device.query import GetDevice
from keeper.equipment.features.get_device.route import router

__all__ = ["GetDevice", "Handler", "bind", "router"]
