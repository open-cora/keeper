"""Behaviour every `IdempotencyStore` adapter owes its callers.

Sibling of the event-store contract in this package, for the same
reason and with the same shape: one set of checks, two adapters, one
tuple both drivers parametrize over.

This port needed it more. The Postgres adapter had no test of its own at
all, only whatever the Access slices happened to drive through it, and
the in-memory twin's docstring promised "the same `(principal_id, key,
surface_id)` namespacing, same claim and finalize semantics, same
stale-lock recovery rules" with nothing anywhere checking the promise.

Two checks take `lock_stale_seconds` or `ttl_hours` of zero rather than
waiting out a real interval. Both adapters compare a stored timestamp
against one taken now, and the stored one was written by an earlier
statement, so zero makes every existing row eligible without a sleep.
"""

from collections.abc import Awaitable, Callable
from uuid import uuid4

from keeper.infrastructure.ports.idempotency_store import (
    CachedError,
    CachedSuccess,
    Claimed,
    HashConflict,
    IdempotencyStore,
    LockedRecent,
)

Check = Callable[[IdempotencyStore], Awaitable[None]]
"""One behaviour, applied to whichever adapter the driver supplies."""

_HOLD = 300
"""A lock-stale window wide enough that nothing goes stale mid-check."""


async def check_a_fresh_key_is_claimed(store: IdempotencyStore) -> None:
    outcome = await store.claim(uuid4(), "k", uuid4(), "hash", "DoThing", lock_stale_seconds=_HOLD)
    assert isinstance(outcome, Claimed)


async def check_a_second_claim_while_the_first_is_in_flight_is_told_to_wait(
    store: IdempotencyStore,
) -> None:
    """The first caller holds the lock and has not finished yet, so the
    second is neither given the work nor given an answer.
    """
    principal, surface = uuid4(), uuid4()
    await store.claim(principal, "k", surface, "hash", "DoThing", lock_stale_seconds=_HOLD)

    outcome = await store.claim(
        principal, "k", surface, "hash", "DoThing", lock_stale_seconds=_HOLD
    )
    assert isinstance(outcome, LockedRecent)


async def check_a_finished_call_replays_the_result_it_returned(
    store: IdempotencyStore,
) -> None:
    principal, surface = uuid4(), uuid4()
    await store.claim(principal, "k", surface, "hash", "DoThing", lock_stale_seconds=_HOLD)
    await store.finalize_success(principal, "k", surface, {"id": "42"})

    outcome = await store.claim(
        principal, "k", surface, "hash", "DoThing", lock_stale_seconds=_HOLD
    )
    assert isinstance(outcome, CachedSuccess)
    assert outcome.result == {"id": "42"}
    assert outcome.command_name == "DoThing"


async def check_a_finished_failure_replays_the_error_it_raised(
    store: IdempotencyStore,
) -> None:
    """A refusal is an answer too. Re-running the work on retry would let
    a deterministic 400 turn into a second attempt at the same mistake.
    """
    principal, surface = uuid4(), uuid4()
    await store.claim(principal, "k", surface, "hash", "DoThing", lock_stale_seconds=_HOLD)
    await store.finalize_error(principal, "k", surface, "InvalidThingError", "no such thing")

    outcome = await store.claim(
        principal, "k", surface, "hash", "DoThing", lock_stale_seconds=_HOLD
    )
    assert isinstance(outcome, CachedError)
    assert outcome.error_type == "InvalidThingError"
    assert outcome.error_msg == "no such thing"


async def check_a_finished_key_reused_with_a_different_command_is_refused(
    store: IdempotencyStore,
) -> None:
    """No cached answer can be the right one for a body that differs."""
    principal, surface = uuid4(), uuid4()
    await store.claim(principal, "k", surface, "first", "DoThing", lock_stale_seconds=_HOLD)
    await store.finalize_success(principal, "k", surface, {"id": "42"})

    outcome = await store.claim(
        principal, "k", surface, "second", "DoThing", lock_stale_seconds=_HOLD
    )
    assert isinstance(outcome, HashConflict)
    assert outcome.expected_hash == "first"
    assert outcome.actual_hash == "second"


async def check_the_same_key_under_a_different_principal_is_a_separate_claim(
    store: IdempotencyStore,
) -> None:
    """Keys are chosen by callers, so two of them will collide eventually.
    Collapsing the namespace would hand one caller another's answer.
    """
    surface = uuid4()
    first = uuid4()
    await store.claim(first, "k", surface, "hash", "DoThing", lock_stale_seconds=_HOLD)
    await store.finalize_success(first, "k", surface, {"id": "first"})

    outcome = await store.claim(uuid4(), "k", surface, "hash", "DoThing", lock_stale_seconds=_HOLD)
    assert isinstance(outcome, Claimed), "the second caller was handed the first one's row"


async def check_the_same_key_on_a_different_surface_is_a_separate_claim(
    store: IdempotencyStore,
) -> None:
    """One caller retrying over HTTP and over MCP is two requests, and the
    surface is the third part of the key that keeps them apart.
    """
    principal = uuid4()
    await store.claim(principal, "k", uuid4(), "hash", "DoThing", lock_stale_seconds=_HOLD)

    outcome = await store.claim(
        principal, "k", uuid4(), "hash", "DoThing", lock_stale_seconds=_HOLD
    )
    assert isinstance(outcome, Claimed)


async def check_a_lock_left_behind_by_a_dead_worker_is_taken_over(
    store: IdempotencyStore,
) -> None:
    """A process that dies mid-request leaves a lock nobody will finalize.
    Without takeover that key is unusable until somebody prunes it.
    """
    principal, surface = uuid4(), uuid4()
    await store.claim(principal, "k", surface, "hash", "DoThing", lock_stale_seconds=_HOLD)

    outcome = await store.claim(principal, "k", surface, "hash", "DoThing", lock_stale_seconds=0)
    assert isinstance(outcome, Claimed)


async def check_prune_drops_a_finished_row_and_keeps_one_in_flight(
    store: IdempotencyStore,
) -> None:
    """Pruning a row somebody still holds would let their work run twice."""
    principal, surface = uuid4(), uuid4()
    await store.claim(principal, "done", surface, "hash", "DoThing", lock_stale_seconds=_HOLD)
    await store.finalize_success(principal, "done", surface, {"id": "42"})
    await store.claim(principal, "busy", surface, "hash", "DoThing", lock_stale_seconds=_HOLD)

    assert await store.prune(ttl_hours=0) == 1

    still_held = await store.claim(
        principal, "busy", surface, "hash", "DoThing", lock_stale_seconds=_HOLD
    )
    assert isinstance(still_held, LockedRecent), "an in-flight claim was pruned"
    reclaimable = await store.claim(
        principal, "done", surface, "hash", "DoThing", lock_stale_seconds=_HOLD
    )
    assert isinstance(reclaimable, Claimed), "the finished row outlived the prune"


CHECKS: tuple[Check, ...] = (
    check_a_fresh_key_is_claimed,
    check_a_second_claim_while_the_first_is_in_flight_is_told_to_wait,
    check_a_finished_call_replays_the_result_it_returned,
    check_a_finished_failure_replays_the_error_it_raised,
    check_a_finished_key_reused_with_a_different_command_is_refused,
    check_the_same_key_under_a_different_principal_is_a_separate_claim,
    check_the_same_key_on_a_different_surface_is_a_separate_claim,
    check_a_lock_left_behind_by_a_dead_worker_is_taken_over,
    check_prune_drops_a_finished_row_and_keeps_one_in_flight,
)
"""Every check above. Hand-written; the drivers guard against omissions."""


def checks_defined_but_not_listed() -> frozenset[str]:
    """Check functions defined in this module that `CHECKS` leaves out.

    The tuple is the contract; a function absent from it runs nowhere.
    Deriving the other side from the module's own namespace means adding
    a check and forgetting to list it fails, rather than passing quietly
    with one behaviour fewer than the file appears to promise.
    """
    listed = {check.__name__ for check in CHECKS}
    defined = {
        name for name, value in globals().items() if name.startswith("check_") and callable(value)
    }
    return frozenset(defined - listed)
