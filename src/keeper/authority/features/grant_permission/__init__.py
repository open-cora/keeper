"""The grant_permission slice, re-exported so callers read `grant_permission.bind`."""

from keeper.authority.features.grant_permission.command import GrantPolicyPermission
from keeper.authority.features.grant_permission.decider import decide
from keeper.authority.features.grant_permission.handler import Handler, bind
from keeper.authority.features.grant_permission.route import router

__all__ = [
    "GrantPolicyPermission",
    "Handler",
    "bind",
    "decide",
    "router",
]
