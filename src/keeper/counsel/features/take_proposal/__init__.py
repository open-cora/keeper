"""The take_proposal slice, re-exported so callers read `.bind`."""

from keeper.counsel.features.take_proposal.command import TakeProposal
from keeper.counsel.features.take_proposal.context import TakeProposalContext
from keeper.counsel.features.take_proposal.decider import decide
from keeper.counsel.features.take_proposal.handler import Handler, bind
from keeper.counsel.features.take_proposal.route import router

__all__ = [
    "Handler",
    "TakeProposal",
    "TakeProposalContext",
    "bind",
    "decide",
    "router",
]
