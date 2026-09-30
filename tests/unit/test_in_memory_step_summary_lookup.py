"""The fold-everything gap lookup, against the contract both adapters keep.

This is the side that answers when there is no database, which is the
environment the unit and contract tiers run in. It reaches its answer by
replaying every execution stream for the steps that named a run and
every dataset stream for the steps something holds, which is nothing
like the single filtered SELECT the Postgres side runs.

The subtraction is where they differ most, and where a mistake is
quietest. Here the filed steps are a set built in Python and removed
from a list; there they are a null column the query tests. An adapter
that lost its grip on either half still returns a page.
"""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from keeper.execution.adapters.in_memory_step_summary_lookup import InMemoryStepSummaryLookup
from keeper.infrastructure.adapters.in_memory_event_store import InMemoryEventStore
from keeper.infrastructure.ports.event_store import EventStore
from keeper.shared.identifier import Identifier
from tests._port_contracts._writers import EventStoreDatasetWriter, EventStoreExecutionWriter
from tests._port_contracts.step_summary_lookup import (
    CHECKS,
    Check,
    checks_defined_but_not_listed,
)

pytestmark = pytest.mark.unit


class _BothWriter:
    """One writer over the two contexts this read model spans.

    The contract needs executions and datasets in one store, and the
    two existing writers each know one. Holding both is the whole of
    it: no behaviour here, so nothing this composes can disagree with
    what the handlers write.

    One execution writer rather than one per verb. It tracks a stream's
    version so a caller does not have to count appends, and two of them
    over one store each believe they are the only writer.
    """

    def __init__(self, event_store: EventStore) -> None:
        executions = EventStoreExecutionWriter(event_store)
        self.dispatch = executions.dispatch
        self.step = executions.step
        self.register = EventStoreDatasetWriter(event_store).register


def test_the_step_summary_contract_lists_at_least_one_check() -> None:
    """Guard the enumeration: an empty parameter set skips, it does not fail."""
    assert CHECKS, "The step summary contract is empty, so both drivers check nothing."


def test_every_step_summary_check_written_is_a_check_that_runs() -> None:
    unlisted = checks_defined_but_not_listed()
    assert not unlisted, (
        f"Defined but missing from CHECKS: {sorted(unlisted)}.\n"
        "A check absent from the tuple runs against neither adapter."
    )


@pytest.mark.parametrize("check", CHECKS, ids=lambda c: c.__name__)
async def test_the_in_memory_step_summary_lookup_keeps_the_port_contract(check: Check) -> None:
    event_store = InMemoryEventStore()
    await check(InMemoryStepSummaryLookup(event_store), _BothWriter(event_store))


async def test_a_dataset_naming_a_step_of_another_execution_still_fills_that_step() -> None:
    """The join runs on the step alone, and the step id is what is unique.

    A dataset carries both ids and only one of them identifies the
    step. An adapter that matched on the pair would leave a filed run
    showing as a gap whenever the two disagreed, which is a
    contradiction the write side already refuses and this must not
    reintroduce as a silent wrong answer.
    """
    event_store = InMemoryEventStore()
    writer = _BothWriter(event_store)
    execution_id, step_ids = uuid4(), [uuid4()]
    at = datetime(2026, 3, 1, 9, 0, tzinfo=UTC)

    await writer.dispatch(
        execution_id=execution_id,
        procedure_id=uuid4(),
        steps=["run tomo_scan"],
        at=at,
        step_ids=step_ids,
    )
    await writer.step(execution_id=execution_id, index=0, at=at, engine_reference="/data/a.h5")
    await writer.register(
        dataset_id=uuid4(),
        execution_id=uuid4(),
        step_id=step_ids[0],
        external_ref=Identifier(scheme="posix-file", value="/data/a.h5"),
        at=at,
    )

    page = await InMemoryStepSummaryLookup(event_store).list_steps_without_datasets(
        beamline=None, limit=10, cursor=None
    )

    assert page.items == []
