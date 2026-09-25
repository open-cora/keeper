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

## Why no status

Nothing withdraws, moves or supersedes a dataset yet, so a status would
have one reachable value, and a one-valued field says less than no field
while inviting a reader to believe a lifecycle is being enforced. It
arrives with the command that flips it, the way a plan's would.

That is also the answer to the obvious question about a moved node. A
record saying where data was at a moment stays true when the data moves;
what changes is that there is a later fact, and a later fact is an event
rather than an edit.
"""

from dataclasses import dataclass
from uuid import UUID

from keeper.shared.identifier import Identifier


class DatasetNotFoundError(Exception):
    """A query named a dataset id with no stream behind it."""

    def __init__(self, dataset_id: UUID) -> None:
        super().__init__(f"Dataset {dataset_id} not found")
        self.dataset_id = dataset_id


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
    """A body of data one acquisition produced, as the fold leaves it.

    ## Why this points at a step and not at a whole execution

    An execution may hold a thousand steps and acquire several times, and
    each acquisition produces its own data. A reference to the execution
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

    `external_ref` is what the store holding the data calls it. That
    stays a reference outward, unresolved on purpose, for the reason a
    run's did.
    """

    id: UUID
    execution_id: UUID
    step_id: UUID
    external_ref: Identifier


__all__ = [
    "Dataset",
    "DatasetAlreadyExistsError",
    "DatasetNotFoundError",
]
