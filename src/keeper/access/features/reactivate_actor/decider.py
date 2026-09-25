"""The decision: what reactivating an actor produces.

Update-style, and the mirror of the deactivating decider. Pure: no
awaits, no ports, no clock.
"""

from datetime import datetime

from keeper.access.aggregates.actor import (
    Actor,
    ActorCannotBeReactivatedError,
    ActorNotFoundError,
    ActorReactivated,
)
from keeper.access.features.reactivate_actor.command import ReactivateActor


def decide(
    state: Actor | None,
    command: ReactivateActor,
    *,
    now: datetime,
) -> list[ActorReactivated]:
    """Decide the events produced by reactivating an actor.

    Invariants:
      - State must not be None, or no such actor was registered
        -> ActorNotFoundError
      - The actor must currently be inactive
        -> ActorCannotBeReactivatedError

    A reactivation emits its own event rather than retracting the
    deactivation that preceded it. The log is append-only, so the way
    back is forward: the stream keeps both facts and the fold reports
    where they leave the actor.
    """
    if state is None:
        raise ActorNotFoundError(command.actor_id)
    if state.active:
        raise ActorCannotBeReactivatedError(command.actor_id)
    return [ActorReactivated(actor_id=command.actor_id, occurred_at=now)]


__all__ = ["decide"]
