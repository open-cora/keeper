"""The fold-everything inquiry reader, against the contract both adapters keep.

The side that answers when there is no database, and it reaches its answers
by replaying every inquiry stream, which is nothing like what the Postgres
side does. The shared suite is the only thing that makes "they answer alike"
a checkable claim.

This adapter takes the status straight off the fold, where the other derives
it from two nullable columns. That divergence is the one most likely to go
unnoticed, because both are right on the states a test writes by habit and
disagree on the one nobody thinks to write: an inquiry answered without ever
being claimed. The shared suite carries that case.
"""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from keeper.counsel.adapters.in_memory_inquiry_summary_lookup import (
    InMemoryInquirySummaryLookup,
)
from keeper.infrastructure.adapters.in_memory_event_store import InMemoryEventStore
from tests._port_contracts._writers import EventStoreInquiryWriter, EventStoreProposalWriter
from tests._port_contracts.inquiry_summary_lookup import (
    CHECKS,
    Check,
    checks_defined_but_not_listed,
)

pytestmark = pytest.mark.unit


def test_the_inquiry_summary_contract_lists_at_least_one_check() -> None:
    """Guard the enumeration: an empty parameter set skips, it does not fail."""
    assert CHECKS, "The inquiry summary contract is empty, so both drivers check nothing."


def test_every_inquiry_summary_check_written_is_a_check_that_runs() -> None:
    unlisted = checks_defined_but_not_listed()
    assert not unlisted, (
        f"Defined but missing from CHECKS: {sorted(unlisted)}.\n"
        "A check absent from the tuple runs against neither adapter."
    )


@pytest.mark.parametrize("check", CHECKS, ids=lambda c: c.__name__)
async def test_the_in_memory_inquiry_summary_lookup_keeps_the_port_contract(
    check: Check,
) -> None:
    event_store = InMemoryEventStore()
    await check(InMemoryInquirySummaryLookup(event_store), EventStoreInquiryWriter(event_store))


async def test_a_proposal_stream_in_the_same_store_is_not_read_as_an_inquiry() -> None:
    """Both aggregates of this context share one store, and this adapter
    enumerates it. Enumerating by stream type is what keeps a proposal out of
    a list of inquiries, and the Postgres side gets that for free from
    subscribing to inquiry event types only. The sibling check next door uses
    a plan for this; a proposal is the sharper case, because the two streams
    are one context apart rather than two."""
    event_store = InMemoryEventStore()
    await EventStoreProposalWriter(event_store).make(
        proposal_id=uuid4(), actor_id=uuid4(), plan_id=uuid4(), at=datetime.now(tz=UTC)
    )
    await EventStoreInquiryWriter(event_store).make(
        inquiry_id=uuid4(),
        actor_id=uuid4(),
        execution_id=uuid4(),
        objective="find the edge",
        execution_step_count=6,
        at=datetime.now(tz=UTC),
    )

    page = await InMemoryInquirySummaryLookup(event_store).list_inquiries(
        status=None, limit=10, cursor=None
    )

    assert len(page.items) == 1
