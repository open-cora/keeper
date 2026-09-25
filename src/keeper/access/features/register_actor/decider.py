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

    The command carries nothing, so that precondition is the whole of
    the decision. `command` is still taken, and still named, because the
    canonical decider signature is what the slice rules range over and
    an underscore here would be a hole in that.
    """
    _ = command
    if state is not None:
        raise ActorAlreadyExistsError(state.id)
    return [ActorRegistered(actor_id=new_id, occurred_at=now)]


__all__ = ["decide"]
