"""Replay Dataset events to reconstruct current state.

`evolve` applies one event. `fold` walks a whole stream from the empty
state, which is what the read path calls after loading rows.

Both are pure and total: the same events in the same order always give
the same state, on any machine, years apart. That is the property the
whole approach rests on, and it is why nothing here reads a clock, a
config value or a database.

The wildcard arm calls `assert_never`, so adding an event class to the
union without handling it here is a type error rather than a state that
silently comes back as None.

## Why the later arms raise on an empty stream

Genesis ignores the state before it. The other two require one, and a
stream whose first row is a replication is a stream no command in this
system could have written. Raising says the log is wrong, where building
a dataset out of the replication would invent an execution and a step
that nothing recorded, and that record would then be indistinguishable
from one somebody meant.
"""

from collections.abc import Sequence
from dataclasses import replace
from typing import assert_never
from uuid import UUID

from keeper.custody.aggregates.dataset.events import (
    DatasetEvent,
    DatasetRegistered,
    DatasetReplicated,
    DatasetWithdrawn,
)
from keeper.custody.aggregates.dataset.state import Dataset
from keeper.shared.identifier import Identifier


def evolve(state: Dataset | None, event: DatasetEvent) -> Dataset:
    """Apply one event to the state before it.

    The genesis arm builds the dataset and ignores the prior state, which
    must be None.

    The reference goes back through `Identifier`, so a row whose scheme or
    value no longer passes the bounds fails here rather than folding into
    a record nothing could have written. That is the same round trip a
    an execution step's reference makes, and it is why events carry the two halves flat
    rather than carrying the pair.

    Replication is written to tolerate an address already held, where
    the decider refuses one. The two are not in disagreement: the
    decider is what a caller meets, and this is what a log meets. A fold
    that doubled an entry on a row some future repair wrote by hand
    would hand every reader a duplicate, and refusing here would make
    the whole stream unreadable over one redundant row.
    """
    match event:
        case DatasetRegistered(
            dataset_id=dataset_id,
            execution_id=execution_id,
            step_id=step_id,
            external_ref_scheme=scheme,
            external_ref_value=value,
        ):
            _ = state
            return Dataset(
                id=dataset_id,
                execution_id=execution_id,
                step_id=step_id,
                external_refs=(Identifier(scheme=scheme, value=value),),
            )
        case DatasetReplicated(
            dataset_id=dataset_id,
            external_ref_scheme=scheme,
            external_ref_value=value,
        ):
            held = _started(state, dataset_id)
            added = Identifier(scheme=scheme, value=value)
            if added in held.external_refs:
                return held
            return replace(held, external_refs=(*held.external_refs, added))
        case DatasetWithdrawn(
            dataset_id=dataset_id,
            external_ref_scheme=scheme,
            external_ref_value=value,
        ):
            held = _started(state, dataset_id)
            gone = Identifier(scheme=scheme, value=value)
            return replace(
                held,
                external_refs=tuple(ref for ref in held.external_refs if ref != gone),
            )
        case _:
            assert_never(event)


def _started(state: Dataset | None, dataset_id: UUID) -> Dataset:
    """The state a later event needs, or a refusal to invent one."""
    if state is None:
        raise DatasetStreamOutOfOrderError(dataset_id)
    return state


class DatasetStreamOutOfOrderError(Exception):
    """A dataset's stream began with something other than its genesis.

    Unreachable through any command here, because every writing slice
    appends at an expected version and only registration appends at
    zero. It exists so the fold says which stream is wrong instead of
    raising an attribute error somewhere further along.
    """

    def __init__(self, dataset_id: UUID) -> None:
        super().__init__(
            f"Dataset {dataset_id} has an event before its registration, so there is "
            "no state for it to change"
        )
        self.dataset_id = dataset_id


def fold(events: Sequence[DatasetEvent]) -> Dataset | None:
    """Replay a stream from the empty state. None means no events at all.

    Takes a `Sequence` rather than a `list` so a caller holding a list of
    one concrete event type can pass it without a cast, which is most
    callers in tests.
    """
    state: Dataset | None = None
    for event in events:
        state = evolve(state, event)
    return state


__all__ = ["DatasetStreamOutOfOrderError", "evolve", "fold"]
