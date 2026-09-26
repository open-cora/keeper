"""The claim_inquiry slice, re-exported so callers read `.bind`."""

from keeper.counsel.features.claim_inquiry.command import ClaimInquiry
from keeper.counsel.features.claim_inquiry.decider import decide
from keeper.counsel.features.claim_inquiry.handler import Handler, bind
from keeper.counsel.features.claim_inquiry.route import router

__all__ = ["ClaimInquiry", "Handler", "bind", "decide", "router"]
