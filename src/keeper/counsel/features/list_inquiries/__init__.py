"""The list_inquiries slice, re-exported so callers read `.bind`."""

from keeper.counsel.features.list_inquiries.handler import Handler, bind
from keeper.counsel.features.list_inquiries.query import (
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    ListInquiries,
)
from keeper.counsel.features.list_inquiries.route import router

__all__ = [
    "DEFAULT_PAGE_SIZE",
    "MAX_PAGE_SIZE",
    "Handler",
    "ListInquiries",
    "bind",
    "router",
]
