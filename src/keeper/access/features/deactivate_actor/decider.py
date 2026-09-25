"""The decision: what deactivating an actor produces.

Update-style, so the state comes in already folded and `new_id` is
absent: this command names its stream rather than creating one.

Pure. No awaits, no ports, no clock.
"""

from datetime import datetime

from keeper.access.aggregates.actor import (
    Actor,
    ActorCannotBeDeactivatedError,
    ActorDeactivated,
    ActorNotFoundError,
)
from keeper.access.features.deactivate_actor.command import DeactivateActor


def decide(
    state: Actor | None,
    command: DeactivateActor,
    *,
    now: datetime,
) -> list[ActorDeactivated]:
    """Decide the events produced by deactivating an actor.

    Invariants:
      - State must not be None, or no such actor was registered
        -> ActorNotFoundError
      - The actor must currently be active
        -> ActorCannotBeDeactivatedError

    The second refusal is a choice, not a necessity. Returning no events
    would make a repeat call a silent success, and the two callers who
    each think they switched off a live actor would both be told they
    did. A conflict says which of them is working from stale state.
    """
    if state is None:
        raise ActorNotFoundError(command.actor_id)
    if not state.active:
        raise ActorCannotBeDeactivatedError(command.actor_id)
    return [ActorDeactivated(actor_id=command.actor_id, occurred_at=now)]


__all__ = ["decide"]
