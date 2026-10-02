"""Dataset state and its domain errors.

A Dataset is one body of data a run produced, as this system came to know
about it: which run made it, and what the store holding it calls it.

## Why so little

Three fields, and the absences are the design. The store holds the data,
its shape, its size and its metadata, and it is addressable, so anything
copied here would be a second copy of a fact somebody else owns and would
go stale the first time they changed it. What no store holds is which run
produced the data, because the store was told a uid and this system holds
the run. The join is the whole of what this context adds.

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
    """

    id: UUID
    execution_id: UUID
    step_id: UUID
    external_refs: tuple[Identifier, ...]


__all__ = [
    "Dataset",
    "DatasetAddressKnownError",
    "DatasetAddressUnknownError",
    "DatasetAlreadyExistsError",
    "DatasetNotFoundError",
]
