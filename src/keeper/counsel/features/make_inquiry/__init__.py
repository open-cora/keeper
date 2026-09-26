"""The make_inquiry slice, re-exported so callers read `.bind`."""

from keeper.counsel.features.make_inquiry.command import MakeInquiry
from keeper.counsel.features.make_inquiry.context import MakeInquiryContext
from keeper.counsel.features.make_inquiry.decider import decide
from keeper.counsel.features.make_inquiry.handler import (
    Handler,
    IdempotentHandler,
    bind,
)
from keeper.counsel.features.make_inquiry.route import router

__all__ = [
    "Handler",
    "IdempotentHandler",
    "MakeInquiry",
    "MakeInquiryContext",
    "bind",
    "decide",
    "router",
]
