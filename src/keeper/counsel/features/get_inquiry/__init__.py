"""The get_inquiry slice, re-exported so callers read `.bind`."""

from keeper.counsel.features.get_inquiry.handler import Handler, bind
from keeper.counsel.features.get_inquiry.query import GetInquiry
from keeper.counsel.features.get_inquiry.route import router

__all__ = ["GetInquiry", "Handler", "bind", "router"]
