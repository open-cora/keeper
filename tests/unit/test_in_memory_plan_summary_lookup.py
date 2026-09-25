"""The fold-everything plan reader, against the contract both adapters keep.

The run driver's sibling, same rationale: this is the side that answers
when there is no database, and it reaches its answers by replaying every
plan stream, which is nothing like what the Postgres side does.
"""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from keeper.execution.adapters.in_memory_plan_summary_lookup import InMemoryPlanSummaryLookup
from keeper.execution.aggregates.plan.state import PlanName
from keeper.execution.aggregates.procedure.state import ProcedureName
from keeper.infrastructure.adapters.in_memory_event_store import InMemoryEventStore
from tests._port_contracts._writers import EventStorePlanWriter, EventStoreProcedureWriter
from tests._port_contracts.plan_summary_lookup import (
    CHECKS,
    Check,
    checks_defined_but_not_listed,
)

pytestmark = pytest.mark.unit


def test_the_plan_summary_contract_lists_at_least_one_check() -> None:
    """Guard the enumeration: an empty parameter set skips, it does not fail."""
    assert CHECKS, "The plan summary contract is empty, so both drivers check nothing."


def test_every_plan_summary_check_written_is_a_check_that_runs() -> None:
    unlisted = checks_defined_but_not_listed()
    assert not unlisted, (
        f"Defined but missing from CHECKS: {sorted(unlisted)}.\n"
        "A check absent from the tuple runs against neither adapter."
    )


@pytest.mark.parametrize("check", CHECKS, ids=lambda c: c.__name__)
async def test_the_in_memory_plan_summary_lookup_keeps_the_port_contract(check: Check) -> None:
    event_store = InMemoryEventStore()
    await check(InMemoryPlanSummaryLookup(event_store), EventStorePlanWriter(event_store))


async def test_a_procedure_stream_in_the_same_store_is_not_read_as_a_plan() -> None:
    """Every aggregate in the process shares one store, and this adapter
    enumerates it. Enumerating by stream type is what keeps a procedure
    out of a list of plans, and the Postgres side gets that for free from
    subscribing to plan event types only.

    A procedure is the neighbour worth using: it is the other routine in
    this context and it carries a name, so an adapter enumerating by
    anything looser than the stream type would produce a plausible row
    rather than an obviously wrong one."""
    event_store = InMemoryEventStore()
    await EventStoreProcedureWriter(event_store).define(
        procedure_id=uuid4(),
        name=ProcedureName("align_then_scan"),
        steps=1,
        at=datetime.now(tz=UTC),
    )
    await EventStorePlanWriter(event_store).define(
        plan_id=uuid4(), name=PlanName("count"), at=datetime.now(tz=UTC)
    )

    page = await InMemoryPlanSummaryLookup(event_store).list_plans(name=None, limit=10, cursor=None)

    assert len(page.items) == 1
