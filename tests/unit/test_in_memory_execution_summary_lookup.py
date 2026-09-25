"""The fold-everything read adapter, against the contract both adapters keep.

This is the side that answers when there is no database, which is the
environment the unit and contract tiers run in. It reaches its answers by
replaying every execution stream, which is nothing like what the Postgres side
does, so the two agreeing is worth asserting rather than assuming.

The progress count is the place they differ most. Here it is the number
of steps the evolver marked reported; there it is the size of a set the
projection unioned into.
"""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from keeper.execution.adapters.in_memory_execution_summary_lookup import (
    InMemoryExecutionSummaryLookup,
)
from keeper.infrastructure.adapters.in_memory_event_store import InMemoryEventStore
from keeper.infrastructure.slices.envelope import to_new_event
from tests._port_contracts._writers import EventStoreExecutionWriter
from tests._port_contracts.execution_summary_lookup import (
    CHECKS,
    Check,
    checks_defined_but_not_listed,
)

pytestmark = pytest.mark.unit


def test_the_walk_summary_contract_lists_at_least_one_check() -> None:
    """Guard the enumeration: an empty parameter set skips, it does not fail."""
    assert CHECKS, "The execution summary contract is empty, so both drivers check nothing."


def test_every_walk_summary_check_written_is_a_check_that_runs() -> None:
    unlisted = checks_defined_but_not_listed()
    assert not unlisted, (
        f"Defined but missing from CHECKS: {sorted(unlisted)}.\n"
        "A check absent from the tuple runs against neither adapter."
    )


@pytest.mark.parametrize("check", CHECKS, ids=lambda c: c.__name__)
async def test_the_in_memory_walk_summary_lookup_keeps_the_port_contract(check: Check) -> None:
    event_store = InMemoryEventStore()
    await check(InMemoryExecutionSummaryLookup(event_store), EventStoreExecutionWriter(event_store))


async def test_a_run_stream_in_the_same_store_is_not_read_as_a_walk() -> None:
    """Every aggregate in the process shares one store, and this adapter
    enumerates it. Enumerating by stream type is what keeps a run out of a
    list of executions, and the Postgres side gets that for free from
    subscribing to execution event types only."""
    event_store = InMemoryEventStore()
    await event_store.append(
        "Run",
        uuid4(),
        0,
        [
            to_new_event(
                event_type="RunReported",
                payload={"run_id": str(uuid4())},
                occurred_at=datetime.now(tz=UTC),
                event_id=uuid4(),
                command_name="ReportRun",
                correlation_id=uuid4(),
                principal_id=uuid4(),
            )
        ],
    )
    await EventStoreExecutionWriter(event_store).dispatch(
        execution_id=uuid4(),
        procedure_id=uuid4(),
        steps=["move 2bmb:m1 to 0.0"],
        at=datetime.now(tz=UTC),
    )

    page = await InMemoryExecutionSummaryLookup(event_store).list_executions(
        procedure_id=None, beamline=None, status=None, limit=10, cursor=None
    )

    assert len(page.items) == 1
