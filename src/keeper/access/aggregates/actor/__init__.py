"""The Actor aggregate: state, events, evolver, and its read path."""

from keeper.access.aggregates.actor.events import (
    ActorDeactivated,
    ActorEvent,
    ActorReactivated,
    ActorRegistered,
    from_stored,
    to_payload,
)
from keeper.access.aggregates.actor.evolver import evolve, fold
from keeper.access.aggregates.actor.read import (
    ACTOR_STREAM_TYPE,
    load_actor,
    load_actor_with_version,
)
from keeper.access.aggregates.actor.state import (
    Actor,
    ActorAlreadyExistsError,
    ActorCannotBeDeactivatedError,
    ActorCannotBeReactivatedError,
    ActorNotFoundError,
)

__all__ = [
    "ACTOR_STREAM_TYPE",
    "Actor",
    "ActorAlreadyExistsError",
    "ActorCannotBeDeactivatedError",
    "ActorCannotBeReactivatedError",
    "ActorDeactivated",
    "ActorEvent",
    "ActorNotFoundError",
    "ActorReactivated",
    "ActorRegistered",
    "evolve",
    "fold",
    "from_stored",
    "load_actor",
    "load_actor_with_version",
    "to_payload",
]
