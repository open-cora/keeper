"""The in-memory idempotency store, against the contract every adapter keeps.

Sibling of the event-store driver next to it, same rationale. This
adapter's docstring promised it mirrored the Postgres one and nothing
checked the promise, so the wrapper tests that use it were resting on
prose.
"""

import pytest

from keeper.infrastructure.adapters.in_memory_idempotency_store import InMemoryIdempotencyStore
from tests._port_contracts.idempotency_store import CHECKS, Check, checks_defined_but_not_listed

pytestmark = pytest.mark.unit


def test_the_idempotency_contract_lists_at_least_one_check() -> None:
    """Guard the enumeration: an empty parameter set skips, it does not fail."""
    assert CHECKS, "The idempotency contract is empty, so both drivers check nothing."


def test_every_idempotency_check_written_is_a_check_that_runs() -> None:
    unlisted = checks_defined_but_not_listed()
    assert not unlisted, (
        f"Defined but missing from CHECKS: {sorted(unlisted)}.\n"
        "A check absent from the tuple runs against neither adapter."
    )


@pytest.mark.parametrize("check", CHECKS, ids=lambda c: c.__name__)
async def test_the_in_memory_idempotency_store_keeps_the_port_contract(check: Check) -> None:
    await check(InMemoryIdempotencyStore())
