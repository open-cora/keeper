"""Events the Dataset aggregate emits, and the union its evolver dispatches on.

Events live with the aggregate rather than with the slice that emits
them, because they are facts about the aggregate's history. A slice
decides when one happens; the history is not the slice's to own.

Four members. The first is the genesis and the rest are what the alias
and the evolver's `assert_never` were written for: data that moves, that
is withdrawn, or that somebody opened and reported the contents of, is a
later fact on this stream and never an edit to the row that came before.

Registered and withdrawn rather than moved, because a copy and a purge
are two events separated by days and both are true in between. One moved
event would have to be written at a moment nothing distinguishes, and
would say the data left a disk it is still on.

An address rather than a copy, because the two come apart: the same
bytes answer to a local path, an NFS path and a server URI at once, and
the question anything reads this to ask is which of them it can reach
from where it is standing. Counting copies would need this system to
know when two paths are one file, which it cannot.

The external reference travels as two flat strings and is rebuilt into a
pair by the fold, because events carry primitives and that pair is a
value object.

## Why the fourth member's entries are typed and not a list of dicts

The rule is primitives on events, and its narrower carve-out is what
applies: a `dict`-typed field is opaque as a whole, so a carrier mixing
closed leaves with open ones loses the closed ones too. An entry list is
exactly that mix. A path and an extent are closed shapes this system
refuses out of range, and a role is a word from a vocabulary nobody here
owns, so flattening the list would make the bounded halves as unreadable
as the free one. The sibling treatment is what a procedure's steps get,
for the same reason.

An entry's extent nests rather than flattening into prefixed keys,
because it is absent as a whole or present as a whole, and three keys
that must all be null together is a shape a writer can get half right.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, assert_never
from uuid import UUID

from keeper.custody.aggregates.dataset.manifest import Entry, Extent
from keeper.infrastructure.ports.event_store import StoredEvent
from keeper.infrastructure.slices.payload import deserialize_or_raise


@dataclass(frozen=True)
class DatasetRegistered:
    """A body of data one run produced was enrolled in the record.

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


@dataclass(frozen=True)
class DatasetAddressRegistered:
    """A copy of this data was reported at another address.

    Carries no execution and step of its own in the way the genesis
    event does, because those name the run that PRODUCED the data and
    copying it does not produce anything. What it carries instead is an
    optional citation of the work that made the copy, and the optionality
    is the point.

    A copy this system dispatched is a report it is owed, attributable
    to the step that did it. A copy somebody else made is something this
    system was told, attributable to nothing here, and most copies are
    that: facility data movement runs on its own and will never be a
    principal in this record. Absent has to mean absent. A citation
    naming an execution that did not do the copying is worse than none,
    because it reads as a report this system went and asked for.

    The two travel together or not at all, which the decider enforces,
    so a reader never has half a citation to interpret.
    """

    dataset_id: UUID
    external_ref_scheme: str
    external_ref_value: str
    copied_by_execution_id: UUID | None
    copied_by_step_id: UUID | None
    occurred_at: datetime


@dataclass(frozen=True)
class DatasetAddressWithdrawn:
    """A copy of this data is no longer at an address it was at.

    Withdrawn rather than deleted, and the distinction is whose act it
    was. This system did not remove anything and could not. Something
    purged a disk or expired a cache, and this is the hearing, which is
    the same posture the genesis event takes toward data being written.

    No citation, where the sibling has one. A purge is housekeeping that
    no execution is dispatched to perform, so a field for the work that
    did it would be empty on every row anybody could write today. It
    arrives with the first thing that withdraws a copy on purpose.
    """

    dataset_id: UUID
    external_ref_scheme: str
    external_ref_value: str
    occurred_at: datetime


@dataclass(frozen=True)
class DatasetManifestRegistered:
    """Somebody opened a copy of this data and reported what was inside.

    The third kind of later fact, and unlike its two siblings it says
    nothing about where the data is. It says what shapes a reader found
    when it looked, which is the one question a reader standing
    somewhere else cannot answer for itself.

    Registered, for the reason every other verb on this stream is a
    registration: this system did not open anything and could not. A
    program beside the data did, and this is the hearing.

    It cites the copy that was opened, where the withdrawal event cites
    only the address it removes. A dataset is commonly at several
    addresses at once and exactly one of them was read, so a report
    naming none of them would leave a reader unable to tell a
    description of the beamline file from a description of a converted
    copy somewhere else. It is never absent: whatever described this had
    to open something.

    A second report for the same copy is an ordinary later fact rather
    than a correction, and both stay in the log. That is what makes the
    known gap survivable: a scan engine at some of these beamlines
    reopens a finished file to append the rotation angle of each frame,
    so a description taken in that window reports angles that are
    missing and a description taken after does not. Neither row is
    wrong. Each is as of when it was taken, which is what `occurred_at`
    is for.

    `entries` may be empty. A reader that understood the container and
    found nothing worth naming in it is a different answer from a
    reader that did not understand the container, and the second one
    sends no manifest at all.
    """

    dataset_id: UUID
    external_ref_scheme: str
    external_ref_value: str
    convention: str
    entries: tuple[Entry, ...]
    occurred_at: datetime


DatasetEvent = (
    DatasetRegistered
    | DatasetAddressRegistered
    | DatasetAddressWithdrawn
    | DatasetManifestRegistered
)
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
        case DatasetAddressRegistered():
            return {
                "dataset_id": str(event.dataset_id),
                "external_ref_scheme": event.external_ref_scheme,
                "external_ref_value": event.external_ref_value,
                "copied_by_execution_id": _optional_id(event.copied_by_execution_id),
                "copied_by_step_id": _optional_id(event.copied_by_step_id),
                "occurred_at": event.occurred_at.isoformat(),
            }
        case DatasetAddressWithdrawn():
            return {
                "dataset_id": str(event.dataset_id),
                "external_ref_scheme": event.external_ref_scheme,
                "external_ref_value": event.external_ref_value,
                "occurred_at": event.occurred_at.isoformat(),
            }
        case DatasetManifestRegistered():
            return {
                "dataset_id": str(event.dataset_id),
                "external_ref_scheme": event.external_ref_scheme,
                "external_ref_value": event.external_ref_value,
                "convention": event.convention,
                "entries": [_entry_to_payload(entry) for entry in event.entries],
                "occurred_at": event.occurred_at.isoformat(),
            }
        case _:
            assert_never(event)


def _entry_to_payload(entry: Entry) -> dict[str, Any]:
    """Render one entry as the primitives that get stored.

    The shapes go out as lists because that is what JSON has, and come
    back as tuples because the value object is frozen. Absence stays
    null at every level rather than becoming an empty list, so a reader
    years from now can tell a container nobody measured from one
    measured as holding nothing.
    """
    extent = entry.extent
    return {
        "path": entry.path,
        "role": entry.role,
        "extent": None
        if extent is None
        else {
            "shape": list(extent.shape),
            "capacity": None if extent.capacity is None else list(extent.capacity),
            "dtype": extent.dtype,
        },
    }


def _entry_from_payload(raw: dict[str, Any]) -> Entry:
    """Rebuild one entry from its stored form.

    The value objects validate on construction, so a row holding an
    entry outside the bounds fails here rather than folding into a
    description nothing could have written. `InvalidManifestError` is a
    `ValueError`, which is why the arm that calls this opts into that
    class the same way the arms rebuilding a reference do.
    """
    extent = raw["extent"]
    return Entry(
        path=raw["path"],
        extent=None
        if extent is None
        else Extent(
            shape=tuple(int(dimension) for dimension in extent["shape"]),
            capacity=(
                None
                if extent["capacity"] is None
                else tuple(int(dimension) for dimension in extent["capacity"])
            ),
            dtype=extent["dtype"],
        ),
        role=raw["role"],
    )


def _optional_id(value: UUID | None) -> str | None:
    """A uuid as a string, or None kept as None.

    Kept rather than rendered as an empty string, so a payload says
    nothing cited it instead of citing something with no name.
    """
    return None if value is None else str(value)


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
        case "DatasetAddressRegistered":
            return deserialize_or_raise(
                "DatasetAddressRegistered",
                lambda: DatasetAddressRegistered(
                    dataset_id=UUID(payload["dataset_id"]),
                    external_ref_scheme=payload["external_ref_scheme"],
                    external_ref_value=payload["external_ref_value"],
                    copied_by_execution_id=_from_optional_id(payload["copied_by_execution_id"]),
                    copied_by_step_id=_from_optional_id(payload["copied_by_step_id"]),
                    occurred_at=datetime.fromisoformat(payload["occurred_at"]),
                ),
                extra=(ValueError,),
            )
        case "DatasetAddressWithdrawn":
            return deserialize_or_raise(
                "DatasetAddressWithdrawn",
                lambda: DatasetAddressWithdrawn(
                    dataset_id=UUID(payload["dataset_id"]),
                    external_ref_scheme=payload["external_ref_scheme"],
                    external_ref_value=payload["external_ref_value"],
                    occurred_at=datetime.fromisoformat(payload["occurred_at"]),
                ),
                extra=(ValueError,),
            )
        case "DatasetManifestRegistered":
            return deserialize_or_raise(
                "DatasetManifestRegistered",
                lambda: DatasetManifestRegistered(
                    dataset_id=UUID(payload["dataset_id"]),
                    external_ref_scheme=payload["external_ref_scheme"],
                    external_ref_value=payload["external_ref_value"],
                    convention=payload["convention"],
                    entries=tuple(_entry_from_payload(raw) for raw in payload["entries"]),
                    occurred_at=datetime.fromisoformat(payload["occurred_at"]),
                ),
                extra=(ValueError,),
            )
        case unknown:
            msg = f"Unknown Dataset event_type: {unknown!r}"
            raise ValueError(msg)


def _from_optional_id(raw: Any) -> UUID | None:
    """A stored id back to a uuid, with absence preserved.

    A row written before anything cited a copy has the key present and
    null rather than missing, because `to_payload` always writes it.
    """
    return None if raw is None else UUID(str(raw))


__all__ = [
    "DatasetAddressRegistered",
    "DatasetAddressWithdrawn",
    "DatasetEvent",
    "DatasetManifestRegistered",
    "DatasetRegistered",
    "from_stored",
    "to_payload",
]
