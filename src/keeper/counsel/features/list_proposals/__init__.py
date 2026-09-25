"""The list_proposals slice, re-exported so callers read `list_proposals.bind`."""

from keeper.counsel.features.list_proposals.handler import Handler, bind
from keeper.counsel.features.list_proposals.query import (
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    ListProposals,
)
from keeper.counsel.features.list_proposals.route import router

__all__ = [
    "DEFAULT_PAGE_SIZE",
    "MAX_PAGE_SIZE",
    "Handler",
    "ListProposals",
    "bind",
    "router",
]
