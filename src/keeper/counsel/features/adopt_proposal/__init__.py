"""The adopt_proposal slice, re-exported so callers read `.bind`."""

from keeper.counsel.features.adopt_proposal.command import AdoptProposal
from keeper.counsel.features.adopt_proposal.decider import decide
from keeper.counsel.features.adopt_proposal.handler import (
    Handler,
    IdempotentHandler,
    bind,
)
from keeper.counsel.features.adopt_proposal.route import router

__all__ = [
    "AdoptProposal",
    "Handler",
    "IdempotentHandler",
    "bind",
    "decide",
    "router",
]
