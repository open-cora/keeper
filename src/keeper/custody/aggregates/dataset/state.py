"""Dataset state and its domain errors.

A Dataset is one body of data a run produced, as this system came to know
about it: which run made it, and what the store holding it calls it.

## Why so little

Four fields, and the absences are still the design. The store holds the
data, its size and its metadata, and it is addressable, so anything
copied here would be a second copy of a fact somebody else owns and
would go stale the first time they changed it. What no store holds is
which run produced the data, because the store was told a uid and this
system holds the run. The join is what this context was built to add.

## The clause that was reversed, and the conditions it rests on

That paragraph used to refuse a dataset's shape alongside its size and
its metadata, and the fourth field is that refusal narrowed. Recorded
here rather than quietly dropped, because a reversal a reader cannot
see is how a rule turns into folklore.

The clause rested on "and it is addressable", which assumes there is
an owner to go and ask. At the beamlines this serves there is not: the
data sits on a local disk, nothing answers questions about it, and a
reader standing anywhere else cannot open it to learn whether it is
even usable. The refusal was protecting against duplicating a fact
somebody else holds, and here nobody else holds it.

So a description is admitted as the same kind of fact an address
already is. Both say what was true at a moment, both are superseded by
a later event rather than edited, and neither substitutes for reading
the data: one says where it is, the other says what shapes are in it,
and a reader wanting a number still has to go and open it.

What stays refused is anything computed FROM the data, and that part
is enforced by shape rather than by this paragraph. The entry shape
has nowhere to put a mean.

The admission is also expected to narrow again. A deployment whose
store serves structure of its own has an owner for the dimensions, and
a reader asking that store reports the roles and leaves the numbers
out. The entry shape already allows that, so the day it happens costs
no new event.

## Why the reference is opaque, and who owns the shape of it

`external_ref` is the same open-scheme pair a run carries: the scheme
names the vocabulary and the value is opaque to this system. That is not
laziness about validation, it is the layering. How a particular store
spells an address is that store's fact, and a rule stated for one store
reads as a rule derived from one.

It has a consequence worth stating plainly, because it is the failure
mode: a producer that reports the same body of data two ways makes two
records of it, and nothing here can tell. A store whose client reports
one address in two spellings is a real thing rather than a hypothetical.
Settling on one spelling belongs to whatever writes the record, before it
writes it, and `Identifier` does no more than trim and bound what arrives.

## Why addresses are plural, and why that is not a status

One body of data is commonly at two addresses at once. A copy to central
storage leaves the beamline copy in place until something purges it, and
that window is days to weeks, which is exactly the window in which
anything would want to read it. A single field would have to be swapped
at the moment of the copy, and that swap is a lie for as long as both
exist: it says the data left a disk it is still on.

So the record gains and loses addresses, and holds however many are
true at once. A reader asking where the data is gets every answer,
and picks the one it can reach.

What this is still not is a status. There is no withdrawn flag and no
superseded flag, because nothing here would read one: an address this
system can no longer point at is an address that is gone from the tuple,
and a dataset that has run out of them says that by being empty. A field
restating what the tuple already shows would be the one-valued field
this aggregate kept out, with a lifecycle implied on top.

A record saying where data was at a moment stays true when the data
moves. What changes is that there is a later fact, and a later fact is
an event rather than an edit.
"""

from dataclasses import dataclass
from uuid import UUID

from keeper.custody.aggregates.dataset.manifest import Description
from keeper.shared.identifier import Identifier


class DatasetNotFoundError(Exception):
    """A query named a dataset id with no stream behind it."""

    def __init__(self, dataset_id: UUID) -> None:
        super().__init__(f"Dataset {dataset_id} not found")
        self.dataset_id = dataset_id


class DatasetAddressKnownError(Exception):
    """A copy was reported at an address this dataset already carries.

    A conflict rather than a silent no-op, because the two callers who
    reach it mean different things. A producer retrying one report is
    covered before this by the idempotency key, so a caller arriving
    here with the same address is a second producer saying something
    this system was already told, and answering "done" to that would
    hide a store being reported twice under one spelling.
    """

    def __init__(self, dataset_id: UUID, scheme: str, value: str) -> None:
        super().__init__(f"Dataset {dataset_id} is already recorded at {scheme}:{value}")
        self.dataset_id = dataset_id
        self.scheme = scheme
        self.value = value


class DatasetAddressUnknownError(Exception):
    """A copy was withdrawn from an address this dataset does not carry.

    Refused rather than treated as already done. A caller withdrawing an
    address nobody recorded is working from a different idea of where
    the data is than this record holds, and the useful answer tells it
    so rather than confirming a removal that removed nothing.
    """

    def __init__(self, dataset_id: UUID, scheme: str, value: str) -> None:
        super().__init__(f"Dataset {dataset_id} is not recorded at {scheme}:{value}")
        self.dataset_id = dataset_id
        self.scheme = scheme
        self.value = value


class DatasetDescriptionUnchangedError(Exception):
    """A description arrived saying exactly what the record already says.

    Refused rather than appended, which is the same call the address
    sibling makes and for the same reason: delivery is at-least-once,
    the server mints nothing a caller could key a retry on, and a
    redelivered report would otherwise grow the log a row per delivery
    while changing no state.

    What is NOT refused is a description that differs. Looking twice
    and seeing two things is the case this aggregate most needs to
    keep, because the container really does change: a scan engine at
    some of these beamlines reopens a finished file to append the
    rotation angle of each frame, so the second look is the true one
    and the first is the evidence of when it became true.
    """

    def __init__(self, dataset_id: UUID, scheme: str, value: str) -> None:
        super().__init__(
            f"Dataset {dataset_id} already carries that description of {scheme}:{value}"
        )
        self.dataset_id = dataset_id
        self.scheme = scheme
        self.value = value


class DatasetAlreadyExistsError(Exception):
    """Registration was attempted against an id that already has a stream.

    Unreachable through the ordinary path, because a registering handler
    mints a fresh id and a fresh id has no history. It exists so the
    decider states the precondition it relies on rather than assuming it,
    and so a caller supplying its own id is refused instead of writing a
    second genesis event onto a live stream.
    """

    def __init__(self, dataset_id: UUID) -> None:
        super().__init__(f"Dataset {dataset_id} already exists")
        self.dataset_id = dataset_id


@dataclass(frozen=True)
class CopiedBy:
    """The work that made a copy, when this system is what asked for it.

    One object rather than two optional ids beside each other, so that
    half a citation is not a thing a caller or a decider can hold. That
    is the same move the external reference makes, for the same reason:
    a pair whose halves can be set independently will eventually be set
    one at a time.

    Absent is the common case and has to stay meaningful. Facility data
    movement runs on its own and will never be a principal here, so most
    copies are reported by something this system did not dispatch. A
    citation naming an execution that did not do the copying reads as a
    report this system went and asked for, which is worse than no
    citation at all.
    """

    execution_id: UUID
    step_id: UUID


@dataclass(frozen=True)
class Dataset:
    """A body of data one run produced, as the fold leaves it.

    ## Why this points at a step and not at a whole execution

    An execution may hold a thousand steps and run several times, and
    each run produces its own data. A reference to the execution
    alone would say that these five datasets came out of this traversal
    and nothing about which came from where, which at a tomography
    beamline is the sample position: the one thing that makes the data
    interpretable.

    ## Why both ids and not the step alone

    `step_id` is unique and would be enough to look one up. It is not
    enough to CHECK one. A step is an entity inside the Execution
    aggregate rather than a stream of its own, so establishing that it
    exists means loading the execution that holds it, and a reference
    that cannot be verified without a second lookup nobody supplied is a
    reference this system would be taking on trust.

    So the root comes first and the step qualifies it, which is also the
    order every other cross-aggregate reference here reads in: the thing
    with a stream, then the part of it.

    `external_refs` is what each store holding the data calls it. They
    stay references outward, unresolved on purpose, for the reason a
    run's did.

    ## Why a tuple, and what an empty one means

    Ordered by when this system learned of each, because that is the one
    ordering it can honestly supply: it knows nothing about which copy is
    faster, nearer or more durable, and sorting would invent a ranking
    out of a scheme name. A reader wanting a particular store looks for
    its scheme rather than taking the first.

    Empty is reachable and is not a broken record. It says this system
    knew where data was, every copy it knew of is gone, and the run that
    produced it is still named here. That is a more useful thing to hold
    than a deleted row, which would answer the question "what did this
    run produce" with silence.

    ## Why one description and not one per address

    `description` is the latest report of what is inside, whichever copy
    was opened to make it, and absent until something opens one. One
    rather than a map keyed by address, because the copies of a dataset
    are the same bytes by this record's own account, and a reader
    meeting two that disagree has found a copy that is not one.

    The event carries the address it was taken of even so, so the day a
    deployment converts data as it copies it, keeping one description
    per copy is a change to how this is folded rather than a new kind
    of row. History already holds what that fold would need.

    Withdrawing an address does not clear it. What was inside the data
    is still the best statement this system has about what the run
    produced, and it is the only one left once every copy is gone,
    which is the case the empty tuple above exists for.
    """

    id: UUID
    execution_id: UUID
    step_id: UUID
    external_refs: tuple[Identifier, ...]
    description: Description | None


__all__ = [
    "CopiedBy",
    "Dataset",
    "DatasetAddressKnownError",
    "DatasetAddressUnknownError",
    "DatasetAlreadyExistsError",
    "DatasetDescriptionUnchangedError",
    "DatasetNotFoundError",
]
