"""The Proposal aggregate: state, events, evolver, and its two read paths."""

from keeper.counsel.aggregates.proposal.events import (
    ProposalAdopted,
    ProposalEvent,
    ProposalMade,
    ProposalTaken,
    from_stored,
    to_payload,
)
from keeper.counsel.aggregates.proposal.evolver import evolve, fold
from keeper.counsel.aggregates.proposal.read import (
    PROPOSAL_STREAM_TYPE,
    load_proposal,
    load_proposal_with_version,
)
from keeper.counsel.aggregates.proposal.state import (
    InvalidProposalParametersError,
    Proposal,
    ProposalAlreadyExistsError,
    ProposalCannotBeAdoptedError,
    ProposalCannotBeTakenError,
    ProposalNotFoundError,
    ProposalStatus,
)
from keeper.counsel.aggregates.proposal.summary import (
    ProposalSummary,
    ProposalSummaryLookup,
    ProposalSummaryPage,
)

__all__ = [
    "PROPOSAL_STREAM_TYPE",
    "InvalidProposalParametersError",
    "Proposal",
    "ProposalAdopted",
    "ProposalAlreadyExistsError",
    "ProposalCannotBeAdoptedError",
    "ProposalCannotBeTakenError",
    "ProposalEvent",
    "ProposalMade",
    "ProposalNotFoundError",
    "ProposalStatus",
    "ProposalSummary",
    "ProposalSummaryLookup",
    "ProposalSummaryPage",
    "ProposalTaken",
    "evolve",
    "fold",
    "from_stored",
    "load_proposal",
    "load_proposal_with_version",
    "to_payload",
]
