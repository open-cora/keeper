"""What a container holds, as whatever could read it reported.

## Why this is a second copy of shapes that exist elsewhere

The program that reads a container declares these same shapes, and the
two are not shared. Every project in this tree is a complete repository,
so a command's vocabulary is written on both sides of the wire and the
wire is the contract. That is already true of everything else a
producer sends: it builds its own intent, this builds its own command,
and neither has ever imported the other.

What the duplication buys is that this side is the one that refuses. A
manifest written by a reader this tree has never seen meets these
bounds before it becomes a row, and a row is forever.

## The one rule these shapes exist to enforce

    A description must be enough to decide whether to open the data,
    and never enough to answer instead of opening it.

`Entry` has three fields and there is nowhere in it to put a mean, a
sigma or a signal-to-noise ratio. A rule saying so could be read and
ignored. A closed shape cannot, and the test asserting the field names
is what turns adding a fourth into an argument somebody has to come and
make.

## Why this context holds any of it

A cache claims to be the value, and reading it substitutes for reading
the source. An index helps a reader find the value and never
substitutes. The address this aggregate already holds is an index entry
of exactly that kind: it says where, never what, and it is useless
without the thing it points at. A manifest extends that index from
where to where and what shapes, and stays useless the same way.

See the state module for the clause this reverses and the conditions it
reverses it under.
"""

from dataclasses import dataclass
from datetime import datetime

from keeper.shared.identifier import Identifier

MANIFEST_MAX_ENTRIES = 64
"""How many entries one manifest may carry.

Derived from a real container rather than chosen. A 12 GB tomography
file at one of these beamlines holds 140 nodes, 109 of them arrays, and
the honest description of it is eight entries: three arrays and five
regions named and counted. The bound has to leave a real container
comfortable and make dumping a tree impossible, and 64 sits in that gap.

It is a contract rather than a truncation point. A reader meeting a
container with more than this summarizes before it sends, because
keeping the first sixty-four would hand this system something that
looks complete and is not. Refused here rather than trimmed, for the
same reason.
"""

ENTRY_PATH_MAX_LENGTH = 512
"""Long enough for a deep tree, short enough to not be a payload."""

MANIFEST_LABEL_MAX_LENGTH = 64
"""The bound on a convention, a role and an element type.

One constant for three fields because they are one kind of thing: a
short word from a vocabulary this system does not own.
"""


class InvalidManifestError(ValueError):
    """A manifest, entry or extent was built outside what it may hold.

    Raised at construction, so a malformed description fails where it is
    assembled rather than at the append. It is this context's first
    error of its own about something malformed: until a manifest
    arrived, everything here was a reference to data nothing here can
    read, which left nothing to declare ill-formed.
    """


@dataclass(frozen=True)
class Extent:
    """How much of something there is, and of what.

    `shape` carries one of two things and `dtype` says which. With an
    element type this describes an array and the shape is its
    dimensions. Without one it describes a container and the shape is a
    single number: how many files a set holds, how many children a
    region has. Checked below rather than left as a reading convention,
    because a container counted by two numbers is nobody's intent.

    One field rather than two, because a set of files and a region of a
    tree are the same case, a thing and how many are in it. A second
    field would sit empty on every array and this one would sit empty on
    every container.

    `capacity` is what the container reserved, where it says. It is the
    difference between a scan that collected one flat field and a scan
    that meant to collect a hundred, which is worth asking and is
    invisible from `shape` alone. Absent where a format has no such
    notion, which is most of them.

    `dtype` is the element type as the format spells it, carried rather
    than interpreted. The same posture this system takes to every other
    word it did not coin.
    """

    shape: tuple[int, ...]
    capacity: tuple[int, ...] | None
    dtype: str | None

    def __post_init__(self) -> None:
        if any(dimension < 0 for dimension in self.shape):
            raise InvalidManifestError(
                f"a shape counts things, so {self.shape} cannot hold a negative"
            )
        if self.dtype is None and len(self.shape) != 1:
            raise InvalidManifestError(
                f"without an element type this describes a container, and a container is "
                f"counted by one number rather than by {self.shape}"
            )
        if self.capacity is not None and len(self.capacity) != len(self.shape):
            raise InvalidManifestError(
                f"capacity {self.capacity} and shape {self.shape} describe the same thing "
                "and must have the same number of dimensions"
            )
        _refuse_empty(self.dtype, "dtype")


@dataclass(frozen=True)
class Entry:
    """One thing inside a container, and what a convention calls it.

    Three fields, and the absences are the design. Any number computed
    from the data is deliberately unreachable here, which is the rule
    this module exists to make structural rather than an oversight.

    `extent` is absent when whatever described this did not measure it.
    That is not a defect and will become the ordinary case: a store that
    serves structure of its own owns those numbers, and a reader asking
    that store reports the roles and leaves the dimensions to the system
    that can answer them live. Absent means nobody said, which is
    different from a container being empty.

    `role` is what a convention calls this entry, and it is absent
    whenever no convention names it. Absence means nobody knows, never
    that there is nothing. A device with no group states the same
    refusal: inventing one would manufacture a fact.

    Nothing here owns the vocabulary roles are drawn from, and nothing
    should. A free-form `group` in the device register has been
    converging without help, with four beamlines independently saying
    the same word. A word several readers reach for has earned
    agreement, and a word one reader reaches for costs nothing. This is
    the only field in the whole description that no store will ever own,
    which is why it is the one that has to be here.
    """

    path: str
    extent: Extent | None
    role: str | None

    def __post_init__(self) -> None:
        if not self.path.strip():
            raise InvalidManifestError("an entry's path names where it is, so it cannot be blank")
        if len(self.path) > ENTRY_PATH_MAX_LENGTH:
            raise InvalidManifestError(
                f"a path of {len(self.path)} is past {ENTRY_PATH_MAX_LENGTH} "
                "and is becoming a payload"
            )
        _refuse_empty(self.role, "role")


@dataclass(frozen=True)
class Manifest:
    """What is in one body of data, as whatever could read it reports.

    Not the data, and not its metadata either. A manifest lists a
    shipment and is never the shipment.

    `convention` names the vocabulary the entries are drawn from, not
    the way they are addressed. Deliberately not called a scheme: the
    scheme an address carries says how to reach a thing, and this says
    how to read it. A manifest reporting `unknown` is honest and reports
    entries with no roles.

    Several conventions in one record is the expected state rather than
    something to reconcile. The beamlines this serves write different
    formats into different stores, and the field saying which is also
    the field saying that two manifests are not comparable.
    """

    convention: str
    entries: tuple[Entry, ...]

    def __post_init__(self) -> None:
        if not self.convention.strip():
            raise InvalidManifestError(
                "a convention names the vocabulary these entries use, and 'unknown' says "
                "there is none. A blank one says nothing at all."
            )
        if len(self.convention) > MANIFEST_LABEL_MAX_LENGTH:
            raise InvalidManifestError(f"a convention is a short word, not {len(self.convention)}")
        if len(self.entries) > MANIFEST_MAX_ENTRIES:
            raise InvalidManifestError(
                f"{len(self.entries)} entries is past {MANIFEST_MAX_ENTRIES}. A container with "
                "that much in it is summarized before it is described, because a manifest "
                "holding the first few looks complete and is not."
            )


@dataclass(frozen=True)
class Description:
    """A manifest, the copy it was taken of, and when it was taken.

    Three fields rather than a bare manifest, because a manifest on its
    own cannot be judged and the other two are what make it readable
    years later.

    `external_ref` is which copy was opened. A dataset is commonly at
    several addresses at once and a reader opened exactly one of them,
    so a description without it floats free of what it describes. It
    also survives the address being withdrawn, which is when a reader
    most needs to know that the thing described is gone.

    `described_at` is when the container was read. Every event on this
    stream is a statement about a moment and this is no different: an
    address says where data was then, and this says what shapes were in
    it then. Neither goes false when the world moves on, because neither
    claimed to be about now.

    That is also the whole answer to staleness. A container can change
    after it is described, and one kind here does: a scan engine at some
    of these beamlines reopens a finished file to append the rotation
    angle of each frame. A description taken in that window is not
    wrong, it is as-of, and a later description is a later event rather
    than an edit.
    """

    manifest: Manifest
    external_ref: Identifier
    described_at: datetime


def _refuse_empty(label: str | None, field: str) -> None:
    """Absence is None, never a blank string.

    Two spellings of "nobody knows" would make the vocabulary
    impossible to count: one reader sending nothing and another sending
    an empty string would read as two different answers.
    """
    if label is None:
        return
    if not label.strip():
        raise InvalidManifestError(f"{field} is absent as None, not as an empty string")
    if len(label) > MANIFEST_LABEL_MAX_LENGTH:
        raise InvalidManifestError(f"{field} is a short word from a vocabulary, not {len(label)}")


__all__ = [
    "ENTRY_PATH_MAX_LENGTH",
    "MANIFEST_LABEL_MAX_LENGTH",
    "MANIFEST_MAX_ENTRIES",
    "Description",
    "Entry",
    "Extent",
    "InvalidManifestError",
    "Manifest",
]
