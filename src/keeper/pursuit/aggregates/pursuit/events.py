"""Events the Pursuit aggregate emits, and the union its evolver dispatches on.

Events live with the aggregate rather than with the slice that emits them,
because they are facts about the aggregate's history. A slice decides when
one happens; the history is not the slice's to own.

Both members are on the makes side of R8, so neither of their commands
accepts an `occurred_at`. Authorizing a loop and revoking one are both
speech acts, and a speech act happens where it is spoken: there is no
earlier moment out in the world for either record to be late to. That is
the same reading that keeps a timestamp off `make_inquiry` and puts one on
`answer_inquiry`.

The budget rides as a mapping of plain strings to integers rather than as
`Budget`. That is the ordinary rule in docs/reference/modeling.md rather
than a judgement about this field: events carry primitives and the evolver
reconstructs the closed type on the way back out, which is what makes a
dimension that is no longer one of the five fail loudly at the fold instead
of spreading as a bare string.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, assert_never
from uuid import UUID

from keeper.infrastructure.ports.event_store import StoredEvent
from keeper.infrastructure.slices.payload import deserialize_or_raise


@dataclass(frozen=True)
class PursuitStarted:
    """A person authorized a bounded loop toward a goal.

    Started rather than opened, defined or created. Opening is what happens
    to an inquiry and says a thing is now awaiting an answer, which is not
    what this is. Defining is what happens to a plan and a procedure and
    says a shape was written down for later, which is also not what this
    is: a pursuit is running from the moment it exists. Started is the word
    for a loop that begins turning when you say so, and "start a pursuit"
    is the phrase somebody at a beamline would say.

    `actor_id` is whoever authorized it, which is whoever authenticated.
    The handler writes the principal into it, so a caller controls who
    authorized as exactly as much as a caller of `make_proposal` controls
    who advised. This is the field the whole aggregate is built around: a
    standing authorization whose author is not on the record is not an
    authorization.

    `beamline` and `scopes` are the two safety-bearing facts, stated once
    here so that nothing downstream has to infer them. `budget` is what
    bounds the loop, and a pursuit cannot be started without one.

    Nothing here names an execution. A pursuit is authorized before it has
    observed anything, and what it goes on to observe is its own record to
    accumulate rather than something the genesis can know.
    """

    pursuit_id: UUID
    actor_id: UUID
    goal: str
    beamline: str
    scopes: tuple[str, ...]
    budget: Mapping[str, int]
    occurred_at: datetime


@dataclass(frozen=True)
class PursuitWithdrawn:
    """A person revoked the authorization before it ran itself out.

    Withdrawn rather than stopped or cancelled. Stopped is the state rather
    than the act, and three different acts will reach it, so spending the
    word on one of them would leave the other two unnameable. Cancelled
    suggests undoing what was done, and nothing a pursuit already
    dispatched is undone by this: work already at a beamline keeps running,
    and the executions it produced stay on the record exactly as they are.

    What this ends is the authorization, not the work.

    `actor_id` is whoever withdrew it, which need not be whoever started
    it. Two different people is the ordinary case rather than the strange
    one: the person who authorizes an overnight loop is often not the
    person at the beamline when it needs stopping. Both are on the record
    and neither overwrites the other.
    """

    pursuit_id: UUID
    actor_id: UUID
    occurred_at: datetime


PursuitEvent = PursuitStarted | PursuitWithdrawn
"""Every event that can appear on a Pursuit stream.

A new member is a new class added here and to this alias, never a field
bolted onto an event already in the log. Adding one without teaching the
evolver about it is a type error, because the wildcard arm there calls
`assert_never`.
"""


def to_payload(event: PursuitEvent) -> dict[str, Any]:
    """Render an event as the primitives that get stored."""
    match event:
        case PursuitStarted():
            return {
                "pursuit_id": str(event.pursuit_id),
                "actor_id": str(event.actor_id),
                "goal": event.goal,
                "beamline": event.beamline,
                "scopes": list(event.scopes),
                "budget": dict(event.budget),
                "occurred_at": event.occurred_at.isoformat(),
            }
        case PursuitWithdrawn():
            return {
                "pursuit_id": str(event.pursuit_id),
                "actor_id": str(event.actor_id),
                "occurred_at": event.occurred_at.isoformat(),
            }
        case _:
            assert_never(event)


def from_stored(stored: StoredEvent) -> PursuitEvent:
    """Rebuild an event from its stored row.

    `extra` carries `ValueError` because the constructors below raise it on
    malformed input: strings that are not UUIDs, and one that is not a
    timestamp. Without it those escape as themselves, naming the field
    rather than the event.

    Neither the budget's dimensions nor its limits are narrowed here. A
    dimension that is no longer one of the five, and a limit that is no
    longer positive, both fail when the evolver reconstructs `Budget`,
    which is where every other payload value in this tree is re-validated.
    """
    payload = stored.payload
    match stored.event_type:
        case "PursuitStarted":
            return deserialize_or_raise(
                "PursuitStarted",
                lambda: PursuitStarted(
                    pursuit_id=UUID(payload["pursuit_id"]),
                    actor_id=UUID(payload["actor_id"]),
                    goal=str(payload["goal"]),
                    beamline=str(payload["beamline"]),
                    scopes=tuple(str(scope) for scope in payload["scopes"]),
                    budget={
                        str(name): int(limit) for name, limit in dict(payload["budget"]).items()
                    },
                    occurred_at=datetime.fromisoformat(payload["occurred_at"]),
                ),
                extra=(ValueError,),
            )
        case "PursuitWithdrawn":
            return deserialize_or_raise(
                "PursuitWithdrawn",
                lambda: PursuitWithdrawn(
                    pursuit_id=UUID(payload["pursuit_id"]),
                    actor_id=UUID(payload["actor_id"]),
                    occurred_at=datetime.fromisoformat(payload["occurred_at"]),
                ),
                extra=(ValueError,),
            )
        case unknown:
            msg = f"Unknown Pursuit event_type: {unknown!r}"
            raise ValueError(msg)


__all__ = [
    "PursuitEvent",
    "PursuitStarted",
    "PursuitWithdrawn",
    "from_stored",
    "to_payload",
]
