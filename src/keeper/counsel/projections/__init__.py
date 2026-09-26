"""Read models this bounded context maintains, and the call that registers them.

`PROJECTION_NAME` is deliberately not re-exported. Each projection module
defines one and they are different strings, so a package-level name would
have to pick a winner and every importer would be one rename away from
querying the wrong table. Import it from the module whose table you mean.
"""

from keeper.counsel.projections.inquiry_summary import InquirySummaryProjection
from keeper.counsel.projections.proposal_summary import ProposalSummaryProjection
from keeper.counsel.projections.register import register_counsel_projections

__all__ = [
    "InquirySummaryProjection",
    "ProposalSummaryProjection",
    "register_counsel_projections",
]
