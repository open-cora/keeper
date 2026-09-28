"""The decision: what resuming a pursuit produces.

Pure. No awaits, no ports, no clock. `now` and `actor_id` arrive as
parameters precisely so this function has nothing to fetch and nothing to
invent.
"""

from datetime import datetime
from uuid import UUID

from keeper.pursuit.aggregates.pursuit import (
    Pursuit,
    PursuitCannotBeResumedError,
    PursuitResumed,
    PursuitStatus,
)
from keeper.pursuit.features.resume_pursuit.command import ResumePursuit


def decide(
    state: Pursuit,
    command: ResumePursuit,
    *,
    actor_id: UUID,
    now: datetime,
) -> list[PursuitResumed]:
    """Decide the events produced by resuming a pursuit.

    Invariants:
      - The pursuit must be held -> PursuitCannotBeResumedError

    Both other statuses are refused and they are refused for different
    reasons. A running pursuit needs nothing done to it, and a resume that
    quietly succeeded would write a row saying something happened when
    nothing did. A stopped one is the serious case: resuming it would
    restart a loop somebody decided was finished, and if a completed
    pursuit could be resumed then the thinker's Stop would be a suggestion
    rather than a terminal.

    Nobody has to be the person the referral was aimed at, or the person
    who authorized the pursuit. Requiring either would mean a pursuit held
    overnight waits for one particular person to wake up, and the record
    keeps every name anyway: who started it, who resumed it each time, and
    who eventually stopped it.
    """
    if state.status is not PursuitStatus.HELD:
        raise PursuitCannotBeResumedError(command.pursuit_id, state.status)
    return [
        PursuitResumed(
            pursuit_id=command.pursuit_id,
            actor_id=actor_id,
            occurred_at=now,
        )
    ]


__all__ = ["decide"]
