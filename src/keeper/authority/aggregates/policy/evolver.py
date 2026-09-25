"""Replay Policy events to reconstruct current state.

`evolve` applies one event. `fold` walks a whole stream from the empty
state, which is what the read path calls after loading rows.

Both are pure and total: the same events in the same order always give
the same state, on any machine, years apart.

The wildcard arm calls `assert_never`, so adding an event class to the
union without handling it here is a type error rather than a state that
silently comes back as None.
"""

from collections.abc import Sequence
from dataclasses import replace
from typing import assert_never

from keeper.authority.aggregates.policy.events import (
    PolicyDefined,
    PolicyEvent,
    PolicyPermissionGranted,
    PolicyPermissionRevoked,
)
from keeper.authority.aggregates.policy.state import Policy
from keeper.infrastructure.slices.evolver import require_state


def evolve(state: Policy | None, event: PolicyEvent) -> Policy:
    """Apply one event to the state before it.

    The genesis arm builds the policy and ignores the prior state, which
    must be None. Every other arm goes through `require_state`: a
    transition applied to an empty stream means the log is corrupt or is
    being replayed out of order, and saying so beats folding it into a
    state that looks plausible.

    A grant is a set union and a revocation a set difference, rather
    than either assigning the whole set. Applying the same event twice
    therefore lands the same state, which is what lets a replay be
    re-run without checking how far it got.

    Neither arm asks whether the pair was already there. That question
    belongs to the decider, which refuses the command; an evolver that
    also refused would make a stream unreplayable the day the rules
    around it changed.
    """
    match event:
        case PolicyDefined(policy_id=policy_id, permissions=permissions):
            return Policy(id=policy_id, permissions=permissions)
        case PolicyPermissionGranted(permission=permission):
            current = require_state(state, "PolicyPermissionGranted")
            return replace(current, permissions=current.permissions | {permission})
        case PolicyPermissionRevoked(permission=permission):
            current = require_state(state, "PolicyPermissionRevoked")
            return replace(current, permissions=current.permissions - {permission})
        case _:
            assert_never(event)


def fold(events: Sequence[PolicyEvent]) -> Policy | None:
    """Replay a stream from the empty state. None means no events at all."""
    state: Policy | None = None
    for event in events:
        state = evolve(state, event)
    return state


__all__ = ["evolve", "fold"]
