"""The decision: what withdrawing a pursuit produces.

Pure. No awaits, no ports, no clock. `now` and `actor_id` arrive as
parameters precisely so this function has nothing to fetch and nothing to
invent.
"""

from datetime import datetime
from uuid import UUID

from keeper.pursuit.aggregates.pursuit import (
    Pursuit,
    PursuitCannotBeWithdrawnError,
    PursuitWithdrawn,
)
from keeper.pursuit.features.withdraw_pursuit.command import WithdrawPursuit


def decide(
    state: Pursuit,
    command: WithdrawPursuit,
    *,
    actor_id: UUID,
    now: datetime,
) -> list[PursuitWithdrawn]:
    """Decide the events produced by withdrawing a pursuit.

    Invariants:
      - The pursuit must be running -> PursuitCannotBeWithdrawnError

    Refused rather than treated as a no-op that changed nothing. A second
    withdrawal is not a repeat of the first: it would name a second person
    and a second moment, and the record would stop saying who ended the
    authorization. The same reading refuses answering an inquiry twice.

    Nobody has to be the person who started it. A pursuit authorized
    overnight is often stopped by whoever is at the beamline in the
    morning, and requiring the author would mean the one person who cannot
    be reached is the only one who can stop it. What the record keeps is
    both names, neither overwriting the other.

    `state` is required rather than optional, and the handler is what
    turns a missing stream into a 404. That is the split every update
    slice in this tree makes: absence is the surface's to name, and this
    function only decides about a pursuit that exists.
    """
    if not state.is_running:
        raise PursuitCannotBeWithdrawnError(command.pursuit_id, state.status)
    return [
        PursuitWithdrawn(
            pursuit_id=command.pursuit_id,
            actor_id=actor_id,
            occurred_at=now,
        )
    ]


__all__ = ["decide"]
