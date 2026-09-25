"""The two ways to read an Equipment summary.

One port, two implementations, picked at wiring time by whether the
deployment has a connection pool. See `wire.py`.
"""

from keeper.equipment.adapters.in_memory_device_summary_lookup import (
    InMemoryDeviceSummaryLookup,
)
from keeper.equipment.adapters.postgres_device_summary_lookup import (
    PostgresDeviceSummaryLookup,
)

__all__ = ["InMemoryDeviceSummaryLookup", "PostgresDeviceSummaryLookup"]
