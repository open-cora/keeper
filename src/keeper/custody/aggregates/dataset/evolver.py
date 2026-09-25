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
"""

from collections.abc import Sequence
from typing import assert_never

from keeper.custody.aggregates.dataset.events import DatasetEvent, DatasetRegistered
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
                external_ref=Identifier(scheme=scheme, value=value),
            )
        case _:
            assert_never(event)


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


__all__ = ["evolve", "fold"]
