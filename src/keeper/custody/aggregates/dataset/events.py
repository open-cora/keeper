"""Events the Dataset aggregate emits, and the union its evolver dispatches on.

Events live with the aggregate rather than with the slice that emits
them, because they are facts about the aggregate's history. A slice
decides when one happens; the history is not the slice's to own.

One member today. The alias below is still written out, and the evolver
still closes over it with `assert_never`, because the second member is
what those two guards exist for and adding them later means adding them
under pressure. The second member is already foreseeable: data that moves
or is withdrawn is a later fact on this stream, never an edit to the row
below.

The external reference travels as two flat strings and is rebuilt into a
pair by the fold, because events carry primitives and that pair is a
value object.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, assert_never
from uuid import UUID

from keeper.infrastructure.ports.event_store import StoredEvent
from keeper.infrastructure.slices.payload import deserialize_or_raise


@dataclass(frozen=True)
class DatasetRegistered:
    """A body of data one acquisition produced was enrolled in the record.

    Registered rather than defined, and the glossary's read-aloud test is
    what settles it: "define a dataset" sounds like inventing data, which
    this system did not do and could not. The data exists in the store
    whether or not anything here has heard of it, and this event is the
    hearing.

    That makes it the first `register_*` in this tree that DESCRIBES a
    fact rather than making one, which is why it carries an
    `occurred_at` a caller may set where `register_actor` does not. An
    actor's registration is an act performed here; a dataset was written
    somewhere else, at a moment this system was not present for. R8 in
    docs/reference/naming.md draws that line on the makes-versus-describes
    axis rather than on the verb.
    """

    dataset_id: UUID
    execution_id: UUID
    step_id: UUID
    external_ref_scheme: str
    external_ref_value: str
    occurred_at: datetime


DatasetEvent = DatasetRegistered
"""Every event that can appear on a Dataset stream.

A new member is a new class added here and to this alias, never a field
bolted onto an event already in the log. Adding one without teaching the
evolver about it is a type error, because the wildcard arm there calls
`assert_never`.
"""


def to_payload(event: DatasetEvent) -> dict[str, Any]:
    """Render an event as the primitives that get stored."""
    match event:
        case DatasetRegistered():
            return {
                "dataset_id": str(event.dataset_id),
                "execution_id": str(event.execution_id),
                "step_id": str(event.step_id),
                "external_ref_scheme": event.external_ref_scheme,
                "external_ref_value": event.external_ref_value,
                "occurred_at": event.occurred_at.isoformat(),
            }
        case _:
            assert_never(event)


def from_stored(stored: StoredEvent) -> DatasetEvent:
    """Rebuild an event from its stored row.

    `extra` carries `ValueError` because three constructors in the arm
    below raise it on malformed input: two strings that are not UUIDs,
    and one that is not a timestamp. Without it those escape as
    themselves, naming the field rather than the event.
    """
    payload = stored.payload
    match stored.event_type:
        case "DatasetRegistered":
            return deserialize_or_raise(
                "DatasetRegistered",
                lambda: DatasetRegistered(
                    dataset_id=UUID(payload["dataset_id"]),
                    execution_id=UUID(payload["execution_id"]),
                    step_id=UUID(payload["step_id"]),
                    external_ref_scheme=payload["external_ref_scheme"],
                    external_ref_value=payload["external_ref_value"],
                    occurred_at=datetime.fromisoformat(payload["occurred_at"]),
                ),
                extra=(ValueError,),
            )
        case unknown:
            msg = f"Unknown Dataset event_type: {unknown!r}"
            raise ValueError(msg)


__all__ = ["DatasetEvent", "DatasetRegistered", "from_stored", "to_payload"]
