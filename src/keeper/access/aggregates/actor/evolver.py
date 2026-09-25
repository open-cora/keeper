"""Replay Actor events to reconstruct current state.

`evolve` applies one event. `fold` walks a whole stream from the empty
state, which is what the read path calls after loading rows.

Both are pure and total: the same events in the same order always give
the same state, on any machine, years apart. That is the property the
whole approach rests on, and it is why nothing here reads a clock, a
config value or a database.

The wildcard arm calls `assert_never`, so adding an event class to the
union without handling it here is a type error rather than a state that
silently comes back as None.
"""

from collections.abc import Sequence
from dataclasses import replace
from typing import assert_never

from keeper.access.aggregates.actor.events import (
    ActorDeactivated,
    ActorEvent,
    ActorReactivated,
    ActorRegistered,
)
from keeper.access.aggregates.actor.state import Actor
from keeper.infrastructure.slices.evolver import require_state


def evolve(state: Actor | None, event: ActorEvent) -> Actor:
    """Apply one event to the state before it.

    The genesis arm builds the actor and ignores the prior state, which
    must be None. Every other arm goes through `require_state`: a
    transition applied to an empty stream means the log is corrupt or is
    being replayed out of order, and saying so beats folding it into a
    state that looks plausible.
    """
    match event:
        case ActorRegistered(actor_id=actor_id):
            return Actor(id=actor_id, active=True)
        case ActorDeactivated():
            return replace(require_state(state, "ActorDeactivated"), active=False)
        case ActorReactivated():
            return replace(require_state(state, "ActorReactivated"), active=True)
        case _:
            assert_never(event)


def fold(events: Sequence[ActorEvent]) -> Actor | None:
    """Replay a stream from the empty state. None means no events at all.

    Takes a `Sequence` rather than a `list` so a caller holding a list of
    one concrete event type can pass it without a cast, which is most
    callers in tests.
    """
    state: Actor | None = None
    for event in events:
        state = evolve(state, event)
    return state


__all__ = ["evolve", "fold"]
