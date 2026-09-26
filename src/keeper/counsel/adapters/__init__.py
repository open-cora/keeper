"""The two ways to read a Counsel summary, once per read model.

One port per aggregate, two implementations each, picked at wiring time by
whether the deployment has a connection pool. See `wire.py`.
"""

from keeper.counsel.adapters.in_memory_inquiry_summary_lookup import (
    InMemoryInquirySummaryLookup,
)
from keeper.counsel.adapters.in_memory_proposal_summary_lookup import (
    InMemoryProposalSummaryLookup,
)
from keeper.counsel.adapters.postgres_inquiry_summary_lookup import (
    PostgresInquirySummaryLookup,
)
from keeper.counsel.adapters.postgres_proposal_summary_lookup import (
    PostgresProposalSummaryLookup,
)

__all__ = [
    "InMemoryInquirySummaryLookup",
    "InMemoryProposalSummaryLookup",
    "PostgresInquirySummaryLookup",
    "PostgresProposalSummaryLookup",
]
