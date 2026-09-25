"""The get_actor slice, re-exported so callers read `get_actor.bind`."""

from keeper.access.features.get_actor.handler import Handler, bind
from keeper.access.features.get_actor.query import GetActor
from keeper.access.features.get_actor.route import router

__all__ = [
    "GetActor",
    "Handler",
    "bind",
    "router",
]
