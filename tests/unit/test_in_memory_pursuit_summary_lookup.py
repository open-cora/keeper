"""The folding half of the pursuit-summary contract.

No database. Every pursuit stream is folded on every call, which is what
lets the application boot and answer with nothing behind it, and is
precisely the cost the projection next door exists to avoid.

The suite is the same one the Postgres driver runs. That is the whole
arrangement: neither adapter can see the other, and the only reason to
believe they agree is that one set of checks passes against both.
"""

import pytest

from keeper.infrastructure.adapters.in_memory_event_store import InMemoryEventStore
from keeper.pursuit.adapters import InMemoryPursuitSummaryLookup
from tests._port_contracts._writers import EventStorePursuitWriter
from tests._port_contracts.pursuit_summary_lookup import CHECKS, Check

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("check", CHECKS, ids=lambda c: c.__name__)
async def test_the_in_memory_pursuit_summary_lookup_keeps_the_port_contract(
    check: Check,
) -> None:
    event_store = InMemoryEventStore()
    await check(InMemoryPursuitSummaryLookup(event_store), EventStorePursuitWriter(event_store))
