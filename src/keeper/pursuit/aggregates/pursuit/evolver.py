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
    PursuitCharged,
    PursuitEvent,
    PursuitRoundOpened,
    PursuitStarted,
    PursuitWithdrawn,
)
from keeper.pursuit.aggregates.pursuit.state import (
    Budget,
    BudgetDimension,
    InvalidPursuitChargeError,
    Pursuit,
    PursuitBeamline,
    PursuitGoal,
    PursuitRound,
    PursuitStatus,
    validate_scopes,
)


def evolve(state: Pursuit | None, event: PursuitEvent) -> Pursuit:
    """Apply one event to the state before it.

    The genesis arm builds the pursuit and ignores the prior state, which
    must be None. The other three require one: nothing can be withdrawn,
    charged or asked about that was never authorized.

    Charges accumulate rather than replace, so a reporter sending what one
    round spent does not have to know what every round before it spent. The
    arm adds to whatever is there, which is also what makes a redelivered
    charge wrong rather than harmless, and is why the surface that writes
    one is the one place in this context that carries a retry key.

    A charge against a dimension this record computes for itself is refused
    here as well as at the decider. Both checks are the same rule and
    neither is redundant: the decider stops one arriving, and this stops
    one already stored from being counted twice, which is the direction
    that would quietly give a loop more room than it was authorized.

    The round index rides the event rather than being taken from the length
    of what is folded so far. A fold that numbered rounds itself would
    renumber them if one were ever removed, and the number is what a later
    call uses to name the round it is closing.

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
        case PursuitRoundOpened(
            round_index=round_index, execution_id=execution_id, inquiry_id=inquiry_id
        ):
            opening = require_state(state, "PursuitRoundOpened")
            return replace(
                opening,
                rounds=(
                    *opening.rounds,
                    PursuitRound(
                        index=round_index,
                        execution_id=execution_id,
                        inquiry_id=inquiry_id,
                    ),
                ),
            )
        case PursuitCharged(dimension=dimension, amount=amount):
            charged = require_state(state, "PursuitCharged")
            spent = BudgetDimension(dimension)
            if not spent.is_reported:
                raise InvalidPursuitChargeError(
                    charged.id, f"{spent} is counted from this record and cannot be charged"
                )
            return replace(
                charged,
                charged={**charged.charged, spent: charged.charged.get(spent, 0) + amount},
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
