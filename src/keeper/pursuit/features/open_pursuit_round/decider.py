"""The decision: what opening a round produces.

Pure. No awaits, no ports, no clock. `now`, `inquiry_id` and the state
arrive as parameters precisely so this function has nothing to fetch and
nothing to invent.

`now` is here for the budget rather than only for the timestamp, which is
unusual and is the clock dimension's doing. A pursuit bounded in wall
seconds runs out at a moment nobody is present for, so whether it has is a
question about the instant this decision is being made.

There is no context module beside this one, although this slice loads two
sibling aggregates. Neither reaches this function. The execution goes to
Counsel's decider, which declares its own context for it, and the pursuit
is the state. A context holder here would carry nothing.
"""

from datetime import datetime
from uuid import UUID

from keeper.pursuit.aggregates.pursuit import (
    Pursuit,
    PursuitRoundCannotBeOpenedError,
    PursuitRoundOpened,
)
from keeper.pursuit.features.open_pursuit_round.command import OpenPursuitRound


def decide(
    state: Pursuit,
    command: OpenPursuitRound,
    *,
    inquiry_id: UUID,
    now: datetime,
) -> list[PursuitRoundOpened]:
    """Decide the events produced by opening a round.

    Invariants:
      - The pursuit must not have stopped
        -> PursuitRoundCannotBeOpenedError
      - No bounded dimension may have run out
        -> PursuitRoundCannotBeOpenedError
      - No round may already have asked about this execution
        -> PursuitRoundCannotBeOpenedError

    Three refusals on one class, with the cause on the error, because they
    are all the same transition being declined and a caller needs to know
    which one it tripped. They call for opposite responses: a stopped
    pursuit is finished, an exhausted one needs a person, and a repeat
    means the answer is already coming.

    The exhaustion check runs before the round is counted, so a pursuit
    bounded at eight rounds opens eight and refuses the ninth. Checking
    afterwards would give it seven, which is the off-by-one a budget stated
    by a person is least forgiving of.

    The index is the length of what is already there rather than a
    parameter, because a round's number is a fact about the pursuit and not
    something a caller or a handler could know better.

    That the execution exists is NOT checked here. Discovering an absence
    needs the store, and the handler has already refused a round naming one
    that does not.
    """
    if not state.is_running:
        raise PursuitRoundCannotBeOpenedError(command.pursuit_id, "it has stopped")
    exhausted = state.exhausted_by(now=now)
    if exhausted is not None:
        raise PursuitRoundCannotBeOpenedError(
            command.pursuit_id,
            f"it has spent its {exhausted} budget of {state.budget.limits[exhausted]}",
        )
    if state.has_observed(command.execution_id):
        raise PursuitRoundCannotBeOpenedError(
            command.pursuit_id, f"a round already asked about execution {command.execution_id}"
        )
    return [
        PursuitRoundOpened(
            pursuit_id=command.pursuit_id,
            round_index=len(state.rounds),
            execution_id=command.execution_id,
            inquiry_id=inquiry_id,
            occurred_at=now,
        )
    ]


__all__ = ["decide"]
