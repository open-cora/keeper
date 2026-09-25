"""Events the Plan aggregate emits, and the union its evolver dispatches on.

Events live with the aggregate rather than with the slice that emits
them, because they are facts about the aggregate's history. A slice
decides when one happens; the history is not the slice's to own.

One member today. The alias below is still written out, and the evolver
still closes over it with `assert_never`, because the second member is
what those two guards exist for and adding them later means adding them
under pressure.

`parameters_schema` rides the payload as the JSON document it already is.
It is the one dict-typed field here, and dict fields are the case the
immutable-collection rule in docs/reference/modeling.md deliberately does
not cover: a JSON Schema is freeform by nature. The companion defence is
the shallow copy the evolver makes on fold, so the stored payload and the
folded state cannot end up sharing one mutable object.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, assert_never
from uuid import UUID

from keeper.infrastructure.ports.event_store import StoredEvent
from keeper.infrastructure.slices.payload import deserialize_or_raise


@dataclass(frozen=True)
class PlanDefined:
    """A runnable routine was written down here.

    Defined rather than registered. The routine the name points at lives
    in the engine and is not this system's to invent, but the
    plan is: nothing anywhere holds this name paired with this schema
    until this event says so, and the record IS the plan. That is the
    split the genesis verbs draw in the glossary.

    `plan_name`, not `name`. Qualified because the personal-data check
    reads field names and cannot tell a routine's name from a person's;
    an unqualified `name` on an append-only row is the shape that rule
    exists to stop, and the qualifier is what says this one is not that.
    The state keeps the bare `name`, where the aggregate it hangs off
    already supplies the qualifier.
    """

    plan_id: UUID
    plan_name: str
    parameters_schema: dict[str, Any]
    occurred_at: datetime


PlanEvent = PlanDefined
"""Every event that can appear on a Plan stream.

A new member is a new class added here and to this alias, never a field
bolted onto an event already in the log. Adding one without teaching the
evolver about it is a type error, because the wildcard arm there calls
`assert_never`.
"""


def to_payload(event: PlanEvent) -> dict[str, Any]:
    """Render an event as the primitives that get stored."""
    match event:
        case PlanDefined():
            return {
                "plan_id": str(event.plan_id),
                "plan_name": event.plan_name,
                "parameters_schema": event.parameters_schema,
                "occurred_at": event.occurred_at.isoformat(),
            }
        case _:
            assert_never(event)


def from_stored(stored: StoredEvent) -> PlanEvent:
    """Rebuild an event from its stored row.

    `extra` carries `ValueError` because two constructors in the arm
    below raise it on malformed input: a string that is not a UUID, and a
    string that is not a timestamp. Without it those escape as
    themselves, naming the field rather than the event.

    The schema comes back as whatever the row holds, with no check that
    it is still one this system would accept today. It was checked when
    it was written and the row cannot have changed since; re-checking
    here would mean a document the validator later grew stricter about
    could stop its stream from loading at all.
    """
    payload = stored.payload
    match stored.event_type:
        case "PlanDefined":
            return deserialize_or_raise(
                "PlanDefined",
                lambda: PlanDefined(
                    plan_id=UUID(payload["plan_id"]),
                    plan_name=payload["plan_name"],
                    parameters_schema=payload["parameters_schema"],
                    occurred_at=datetime.fromisoformat(payload["occurred_at"]),
                ),
                extra=(ValueError,),
            )
        case unknown:
            msg = f"Unknown Plan event_type: {unknown!r}"
            raise ValueError(msg)


__all__ = ["PlanDefined", "PlanEvent", "from_stored", "to_payload"]
