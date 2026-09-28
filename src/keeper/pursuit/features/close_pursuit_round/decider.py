"""The decision: what closing a round produces.

Pure. No awaits, no ports, no clock. The outcome arrives already worked
out, because working it out means reading an inquiry and a decision
function never reads from a store.

That split is worth naming. What the handler decides is which of the four
the thinker's conclusion answers to, and what to load in consequence. What
this decides is whether the round may be closed at all, and that the
outcome and the ids beside it are consistent. The first is a translation,
the second is the invariant.
"""

from datetime import datetime
from uuid import UUID

from keeper.pursuit.aggregates.pursuit import (
    Pursuit,
    PursuitRoundCannotBeClosedError,
    PursuitRoundClosed,
    RoundOutcome,
)
from keeper.pursuit.features.close_pursuit_round.command import ClosePursuitRound


def decide(
    state: Pursuit,
    command: ClosePursuitRound,
    *,
    outcome: RoundOutcome,
    proposal_id: UUID | None,
    dispatched_id: UUID | None,
    now: datetime,
) -> list[PursuitRoundClosed]:
    """Decide the events produced by closing a round.

    Invariants:
      - The pursuit must be running -> PursuitRoundCannotBeClosedError
      - The round must exist -> PursuitRoundCannotBeClosedError
      - The round must still be open -> PursuitRoundCannotBeClosedError
      - A proposal and a dispatch are present exactly when the outcome
        advances -> PursuitRoundCannotBeClosedError

    The last is the one thing this event could carry wrongly, and it is
    refused in both directions. An advance with nothing dispatched would be
    a pursuit that counted a run against its budget and started none. A
    dispatch on any other outcome would be work at a beamline that the
    record says nobody asked for.

    A closed round is refused rather than treated as a repeat that changed
    nothing, which is the same reading that refuses answering an inquiry
    twice: the second close would name a different outcome and the record
    would stop saying which one the pursuit acted on.

    A held pursuit refuses too, and that is what makes holding mean
    something. Rounds opened before the hold cannot be closed until
    somebody puts the pursuit back to work, so a driver that carried on
    regardless is stopped by the record rather than by its own good
    manners.
    """
    if not state.is_running:
        raise PursuitRoundCannotBeClosedError(
            command.pursuit_id, command.round_index, f"the pursuit is {state.status}"
        )
    turn = state.round_at(command.round_index)
    if turn is None:
        raise PursuitRoundCannotBeClosedError(
            command.pursuit_id, command.round_index, "there is no such round"
        )
    if not turn.is_open:
        raise PursuitRoundCannotBeClosedError(
            command.pursuit_id, command.round_index, f"it already closed as {turn.outcome}"
        )

    dispatching = outcome is RoundOutcome.ADVANCED
    carries_work = proposal_id is not None and dispatched_id is not None
    if dispatching != carries_work:
        raise PursuitRoundCannotBeClosedError(
            command.pursuit_id,
            command.round_index,
            f"{outcome} and the work it cites disagree",
        )

    return [
        PursuitRoundClosed(
            pursuit_id=command.pursuit_id,
            round_index=command.round_index,
            outcome=outcome.value,
            proposal_id=proposal_id,
            dispatched_id=dispatched_id,
            occurred_at=now,
        )
    ]


__all__ = ["decide"]
