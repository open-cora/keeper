"""Events the Operation aggregate emits, and the union its evolver dispatches on.

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
class OperationDefined:
    """A runnable routine was written down here.

    Defined rather than registered. The routine the name points at lives
    in the engine and is not this system's to invent, but the
    operation is: nothing anywhere holds this name paired with this schema
    until this event says so, and the record IS the operation. That is the
    split the genesis verbs draw in the glossary.

    `operation_name`, not `name`. Qualified because the personal-data check
    reads field names and cannot tell a routine's name from a person's;
    an unqualified `name` on an append-only row is the shape that rule
    exists to stop, and the qualifier is what says this one is not that.
    The state keeps the bare `name`, where the aggregate it hangs off
    already supplies the qualifier.
    """

    operation_id: UUID
    operation_name: str
    parameters_schema: dict[str, Any]
    occurred_at: datetime


OperationEvent = OperationDefined
"""Every event that can appear on an Operation stream.

A new member is a new class added here and to this alias, never a field
bolted onto an event already in the log. Adding one without teaching the
evolver about it is a type error, because the wildcard arm there calls
`assert_never`.
"""


def to_payload(event: OperationEvent) -> dict[str, Any]:
    """Render an event as the primitives that get stored."""
    match event:
        case OperationDefined():
            return {
                "operation_id": str(event.operation_id),
                "operation_name": event.operation_name,
                "parameters_schema": event.parameters_schema,
                "occurred_at": event.occurred_at.isoformat(),
            }
        case _:
            assert_never(event)


def from_stored(stored: StoredEvent) -> OperationEvent:
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
        case "OperationDefined":
            return deserialize_or_raise(
                "OperationDefined",
                lambda: OperationDefined(
                    operation_id=UUID(payload["operation_id"]),
                    operation_name=payload["operation_name"],
                    parameters_schema=payload["parameters_schema"],
                    occurred_at=datetime.fromisoformat(payload["occurred_at"]),
                ),
                extra=(ValueError,),
            )
        case unknown:
            msg = f"Unknown Operation event_type: {unknown!r}"
            raise ValueError(msg)


__all__ = ["OperationDefined", "OperationEvent", "from_stored", "to_payload"]
