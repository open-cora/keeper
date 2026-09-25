"""The make_proposal slice, re-exported so callers read `.bind`."""

from keeper.counsel.features.make_proposal.command import MakeProposal
from keeper.counsel.features.make_proposal.context import MakeProposalContext
from keeper.counsel.features.make_proposal.decider import decide
from keeper.counsel.features.make_proposal.handler import (
    Handler,
    IdempotentHandler,
    bind,
)
from keeper.counsel.features.make_proposal.route import router

__all__ = [
    "Handler",
    "IdempotentHandler",
    "MakeProposal",
    "MakeProposalContext",
    "bind",
    "decide",
    "router",
]
