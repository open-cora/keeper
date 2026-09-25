"""Read models this bounded context maintains, and the call that registers them."""

from keeper.counsel.projections.proposal_summary import (
    PROJECTION_NAME,
    ProposalSummaryProjection,
)
from keeper.counsel.projections.register import register_counsel_projections

__all__ = [
    "PROJECTION_NAME",
    "ProposalSummaryProjection",
    "register_counsel_projections",
]
