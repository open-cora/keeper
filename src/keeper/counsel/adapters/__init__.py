"""The two ways to read a Counsel summary.

One port, two implementations, picked at wiring time by whether the
deployment has a connection pool. See `wire.py`.
"""

from keeper.counsel.adapters.in_memory_proposal_summary_lookup import (
    InMemoryProposalSummaryLookup,
)
from keeper.counsel.adapters.postgres_proposal_summary_lookup import (
    PostgresProposalSummaryLookup,
)

__all__ = ["InMemoryProposalSummaryLookup", "PostgresProposalSummaryLookup"]
