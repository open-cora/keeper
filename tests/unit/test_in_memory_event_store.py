"""The in-memory event store, against the contract every adapter keeps.

The double carries the whole unit tier. Every handler test here swaps the
database for this dict, so what those tests prove about a handler holds
only as far as the dict behaves like Postgres. This file is where that
stops being an assumption.

The checks live in `tests/_port_contracts/event_store.py` and the
integration tier runs the same tuple against the real adapter. The two
guards below sit in this tier rather than that one because this tier
always runs: a suite nobody can run is not a guard.
"""

import pytest

from keeper.infrastructure.adapters.in_memory_event_store import InMemoryEventStore
from tests._port_contracts.event_store import CHECKS, Check, checks_defined_but_not_listed

pytestmark = pytest.mark.unit


def test_the_event_store_contract_lists_at_least_one_check() -> None:
    """Guard the enumeration: an empty parameter set skips, it does not fail."""
    assert CHECKS, "The event-store contract is empty, so both drivers check nothing."


def test_every_event_store_check_written_is_a_check_that_runs() -> None:
    unlisted = checks_defined_but_not_listed()
    assert not unlisted, (
        f"Defined but missing from CHECKS: {sorted(unlisted)}.\n"
        "A check absent from the tuple runs against neither adapter."
    )


@pytest.mark.parametrize("check", CHECKS, ids=lambda c: c.__name__)
async def test_the_in_memory_event_store_keeps_the_port_contract(check: Check) -> None:
    await check(InMemoryEventStore())
