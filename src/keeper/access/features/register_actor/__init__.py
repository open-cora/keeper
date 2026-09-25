"""The register_actor slice, re-exported so callers read `register_actor.bind`."""

from keeper.access.features.register_actor.command import RegisterActor
from keeper.access.features.register_actor.decider import decide
from keeper.access.features.register_actor.handler import Handler, IdempotentHandler, bind
from keeper.access.features.register_actor.route import router

__all__ = [
    "Handler",
    "IdempotentHandler",
    "RegisterActor",
    "bind",
    "decide",
    "router",
]
