"""The revoke_permission slice, re-exported so callers read `revoke_permission.bind`."""

from keeper.authority.features.revoke_permission.command import RevokePolicyPermission
from keeper.authority.features.revoke_permission.decider import decide
from keeper.authority.features.revoke_permission.handler import Handler, bind
from keeper.authority.features.revoke_permission.route import router

__all__ = [
    "Handler",
    "RevokePolicyPermission",
    "bind",
    "decide",
    "router",
]
