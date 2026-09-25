"""Adapters this bounded context supplies to its own read port.

Two, the halves of one question. The port is declared with the aggregate
it summarises, because a dataset summary is Custody's to define. The
Postgres half reads the projection a deployment maintains; the in-memory
half folds the streams when there is no database to project into.

Different from Authority's adapters package, which implements a port
declared in infrastructure. This port is declared and implemented in the
same context, because nothing outside Custody has any use for a dataset
summary.
"""

from keeper.custody.adapters.in_memory_dataset_summary_lookup import (
    InMemoryDatasetSummaryLookup,
)
from keeper.custody.adapters.postgres_dataset_summary_lookup import (
    PostgresDatasetSummaryLookup,
)

__all__ = [
    "InMemoryDatasetSummaryLookup",
    "PostgresDatasetSummaryLookup",
]
