"""Events the Actor aggregate emits, and the union its evolver dispatches on.

Events live with the aggregate rather than with the slice that emits them,
because they are facts about the aggregate's history. A slice decides when
one happens; the history is not the slice's to own.

`to_payload` and `from_stored` are the single home for turning an event
into stored primitives and back. A payload carries ids and timestamps and
nothing else, which is what lets the stream stay immutable: nothing in it
is ever going to need taking back out.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, assert_never
from uuid import UUID

from keeper.infrastructure.ports.event_store import StoredEvent
from keeper.infrastructure.slices.payload import deserialize_or_raise


@dataclass(frozen=True)
class ActorRegistered:
    """An actor was added to the system's records.

    Carries the id and when it happened, and nothing else. See the state
    module for why an actor has nothing else to carry.
    """

    actor_id: UUID
    occurred_at: datetime


@dataclass(frozen=True)
class ActorDeactivated:
    """An actor was switched off.

    Carries no reason. A free-text reason is the field most likely to end
    up holding something about a person, in the one table that cannot be
    edited, so it waits for a caller that asks for it by name rather than
    arriving because the shape looked incomplete.
    """

    actor_id: UUID
    occurred_at: datetime


@dataclass(frozen=True)
class ActorReactivated:
    """An actor was switched back on.

    The inverse of `ActorDeactivated`, and a separate fact rather than a
    field flipped back. The stream is the record: how many times an actor
    went off and on, and when, is readable only because each switch left
    its own row.
    """

    actor_id: UUID
    occurred_at: datetime


ActorEvent = ActorRegistered | ActorDeactivated | ActorReactivated
"""Every event that can appear on an Actor stream.

A new member is a new class added here and to this alias, never a field
bolted onto an event already in the log. Adding one without teaching the
evolver about it is a type error, because the wildcard arm there calls
`assert_never`.
"""


def to_payload(event: ActorEvent) -> dict[str, Any]:
    """Render an event as the primitives that get stored."""
    match event:
        case ActorRegistered() | ActorDeactivated() | ActorReactivated():
            return {
                "actor_id": str(event.actor_id),
                "occurred_at": event.occurred_at.isoformat(),
            }
        case _:
            assert_never(event)


def from_stored(stored: StoredEvent) -> ActorEvent:
    """Rebuild an event from its stored row.

    `extra` carries `ValueError` because both constructors in each arm
    below raise it on malformed input: a string that is not a UUID, and a
    string that is not a timestamp. Without it those two escape as
    themselves, naming the field rather than the event.

    The arms are spelled out separately although their bodies match,
    because the event type each produces is the whole difference and a
    shared arm would have to pick one by lookup. A lookup is where a
    typo becomes a wrong event class rather than a failing branch, and
    a wrong class here folds into a wrong state rather than an error.
    """
    payload = stored.payload
    match stored.event_type:
        case "ActorRegistered":
            return deserialize_or_raise(
                "ActorRegistered",
                lambda: ActorRegistered(
                    actor_id=UUID(payload["actor_id"]),
                    occurred_at=datetime.fromisoformat(payload["occurred_at"]),
                ),
                extra=(ValueError,),
            )
        case "ActorDeactivated":
            return deserialize_or_raise(
                "ActorDeactivated",
                lambda: ActorDeactivated(
                    actor_id=UUID(payload["actor_id"]),
                    occurred_at=datetime.fromisoformat(payload["occurred_at"]),
                ),
                extra=(ValueError,),
            )
        case "ActorReactivated":
            return deserialize_or_raise(
                "ActorReactivated",
                lambda: ActorReactivated(
                    actor_id=UUID(payload["actor_id"]),
                    occurred_at=datetime.fromisoformat(payload["occurred_at"]),
                ),
                extra=(ValueError,),
            )
        case unknown:
            msg = f"Unknown Actor event_type: {unknown!r}"
            raise ValueError(msg)


__all__ = [
    "ActorDeactivated",
    "ActorEvent",
    "ActorReactivated",
    "ActorRegistered",
    "from_stored",
    "to_payload",
]
