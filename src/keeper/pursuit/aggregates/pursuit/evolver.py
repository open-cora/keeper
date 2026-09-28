"""Replay Pursuit events to reconstruct current state.

`evolve` applies one event. `fold` walks a whole stream from the empty
state, which is what the read path calls after loading rows.

Both are pure and total: the same events in the same order always give the
same state, on any machine, years apart. That is the property the whole
approach rests on, and it is why nothing here reads a clock, a config value
or a database.

The wildcard arm calls `assert_never`, so adding an event class to the union
without handling it here is a type error rather than a state that silently
comes back as None.
"""

from collections.abc import Sequence
from dataclasses import replace
from typing import assert_never

from keeper.infrastructure.slices.evolver import require_state
from keeper.pursuit.aggregates.pursuit.events import (
    PursuitEvent,
    PursuitStarted,
    PursuitWithdrawn,
)
from keeper.pursuit.aggregates.pursuit.state import (
    Budget,
    BudgetDimension,
    Pursuit,
    PursuitBeamline,
    PursuitGoal,
    PursuitStatus,
    validate_scopes,
)


def evolve(state: Pursuit | None, event: PursuitEvent) -> Pursuit:
    """Apply one event to the state before it.

    The genesis arm builds the pursuit and ignores the prior state, which
    must be None. The other requires one, because nothing can be withdrawn
    that was never authorized.

    Every closed type is reconstructed rather than carried across as the
    primitives the payload holds. That is what re-validates them on read: a
    goal that has outgrown its bound, a beamline that has, a scope list
    that has, and a budget naming a dimension that is no longer one of the
    five all fail here, at the fold, rather than reaching a caller as
    strings nothing checked.

    `started_at` comes off the genesis event rather than off the envelope.
    Both hold the same moment, because the command that produces this event
    accepts no timestamp from its caller, and the one the fold can see is
    the payload's.

    The status is set by which arm ran and is never read off a payload, so
    it cannot contradict the event that produced it.
    """
    match event:
        case PursuitStarted(
            pursuit_id=pursuit_id,
            actor_id=actor_id,
            goal=goal,
            beamline=beamline,
            scopes=scopes,
            budget=budget,
            occurred_at=occurred_at,
        ):
            _ = state
            return Pursuit(
                id=pursuit_id,
                actor_id=actor_id,
                goal=PursuitGoal(goal),
                beamline=PursuitBeamline(beamline),
                scopes=validate_scopes(scopes),
                budget=Budget({BudgetDimension(name): limit for name, limit in budget.items()}),
                started_at=occurred_at,
                status=PursuitStatus.RUNNING,
            )
        case PursuitWithdrawn(actor_id=actor_id):
            return replace(
                require_state(state, "PursuitWithdrawn"),
                status=PursuitStatus.STOPPED,
                stopped_by=actor_id,
            )
        case _:
            assert_never(event)


def fold(events: Sequence[PursuitEvent]) -> Pursuit | None:
    """Replay a stream from the empty state. None means no events at all.

    Takes a `Sequence` rather than a `list` so a caller holding a list of
    one concrete event type can pass it without a cast, which is most
    callers in tests.
    """
    state: Pursuit | None = None
    for event in events:
        state = evolve(state, event)
    return state


__all__ = ["evolve", "fold"]
