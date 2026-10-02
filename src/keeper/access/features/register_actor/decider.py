"""The decision: what registering an actor produces.

Pure. No awaits, no ports, no clock. `now` and `new_id` arrive as
parameters precisely so this function has nothing to invent, which is
what makes the same inputs give the same events on replay.
"""

from datetime import datetime
from uuid import UUID

from keeper.access.aggregates.actor import Actor, ActorAlreadyExistsError, ActorRegistered
from keeper.access.features.register_actor.command import RegisterActor


def decide(
    state: Actor | None,
    command: RegisterActor,
    *,
    now: datetime,
    new_id: UUID,
) -> list[ActorRegistered]:
    """Decide the events produced by registering an actor.

    Invariants:
      - State must be None, or the id already has a history
        -> ActorAlreadyExistsError

    `new_id` is what the actor is registered as when the command names
    no id, which is the ordinary case. A command that names one wins,
    and the precondition above stops being unreachable: a minted id
    cannot collide with a stream that already exists, and a chosen one
    can.
    """
    if state is not None:
        raise ActorAlreadyExistsError(state.id)
    return [ActorRegistered(actor_id=command.actor_id or new_id, occurred_at=now)]


__all__ = ["decide"]
