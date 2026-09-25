"""The fold-everything proposal reader, against the contract both adapters keep.

The side that answers when there is no database, and it reaches its
answers by replaying every proposal stream, which is nothing like what
the Postgres side does. The shared suite is the only thing that makes
"they answer alike" a checkable claim.
"""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from keeper.counsel.adapters.in_memory_proposal_summary_lookup import (
    InMemoryProposalSummaryLookup,
)
from keeper.execution.aggregates.plan.state import PlanName
from keeper.infrastructure.adapters.in_memory_event_store import InMemoryEventStore
from tests._port_contracts._writers import EventStorePlanWriter, EventStoreProposalWriter
from tests._port_contracts.proposal_summary_lookup import (
    CHECKS,
    Check,
    checks_defined_but_not_listed,
)

pytestmark = pytest.mark.unit


def test_the_proposal_summary_contract_lists_at_least_one_check() -> None:
    """Guard the enumeration: an empty parameter set skips, it does not fail."""
    assert CHECKS, "The proposal summary contract is empty, so both drivers check nothing."


def test_every_proposal_summary_check_written_is_a_check_that_runs() -> None:
    unlisted = checks_defined_but_not_listed()
    assert not unlisted, (
        f"Defined but missing from CHECKS: {sorted(unlisted)}.\n"
        "A check absent from the tuple runs against neither adapter."
    )


@pytest.mark.parametrize("check", CHECKS, ids=lambda c: c.__name__)
async def test_the_in_memory_proposal_summary_lookup_keeps_the_port_contract(
    check: Check,
) -> None:
    event_store = InMemoryEventStore()
    await check(InMemoryProposalSummaryLookup(event_store), EventStoreProposalWriter(event_store))


async def test_a_plan_stream_in_the_same_store_is_not_read_as_a_proposal() -> None:
    """Every aggregate in the process shares one store, and this adapter
    enumerates it. Enumerating by stream type is what keeps a plan out of a
    list of proposals, and the Postgres side gets that for free from
    subscribing to proposal event types only."""
    event_store = InMemoryEventStore()
    await EventStorePlanWriter(event_store).define(
        plan_id=uuid4(), name=PlanName("count"), at=datetime.now(tz=UTC)
    )
    await EventStoreProposalWriter(event_store).make(
        proposal_id=uuid4(),
        actor_id=uuid4(),
        plan_id=uuid4(),
        at=datetime.now(tz=UTC),
    )

    page = await InMemoryProposalSummaryLookup(event_store).list_proposals(
        is_open=None, limit=10, cursor=None
    )

    assert len(page.items) == 1
