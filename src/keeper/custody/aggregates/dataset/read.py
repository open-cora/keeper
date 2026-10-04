"""Load a Dataset by replaying its stream.

One function. It loads the stream, rebuilds each event, and folds them
into current state. There is no datasets table: the answer is recomputed
from history on every call.

That is the right trade for reading one dataset by id, where a stream is
a single row today and a handful once data can be withdrawn or moved. It
is the wrong trade for the question this context exists to answer, which
is what a given run produced. That one cannot name a stream, so it cannot
fold one, and it needs a maintained summary table instead. It belongs in
its own module and is not here yet.

Two loaders, and the difference between them is the version. A handler
about to append to a stream that already has rows needs the version it
folded from, so that two callers registering an address at once produce
one append and one conflict rather than two rows saying the same thing.
A reader needs no such thing and gets the shorter function.

The second one arrived with the commands that change where a dataset
can be read, which are the first things to append after a genesis.

Lives with the aggregate rather than with a slice because it reads the
aggregate's whole stream, whatever command happened to write each row.
"""

from uuid import UUID

from keeper.custody.aggregates.dataset.events import from_stored
from keeper.custody.aggregates.dataset.evolver import fold
from keeper.custody.aggregates.dataset.state import Dataset
from keeper.infrastructure.ports.event_store import EventStore

DATASET_STREAM_TYPE = "Dataset"
"""The stream type every Dataset event is stored under.

Half of the `(stream_type, event_type)` routing key. Declared as a
constant because the writing side and this reading side must agree on it
and they are in different files.
"""


async def load_dataset(event_store: EventStore, dataset_id: UUID) -> Dataset | None:
    """Return the dataset's current state, or None if the stream is empty.

    An empty stream means no such dataset was ever registered. The caller
    decides what that means on its own surface: a 404 over HTTP, an error
    result over MCP.
    """
    stored, _version = await event_store.load(DATASET_STREAM_TYPE, dataset_id)
    return fold([from_stored(row) for row in stored])


async def load_dataset_with_version(
    event_store: EventStore, dataset_id: UUID
) -> tuple[Dataset | None, int]:
    """Return the dataset's state and the version it was folded from.

    The version is what a writing handler passes as `expected_version`,
    so that two callers registering an address on one dataset at once
    produce one append and one `ConcurrencyError`. Without it the second
    append would land an address the decider had no chance to refuse,
    because it decided against state that was already stale, and the
    duplicate it was there to catch would be in the log.
    """
    stored, version = await event_store.load(DATASET_STREAM_TYPE, dataset_id)
    return fold([from_stored(row) for row in stored]), version


__all__ = ["DATASET_STREAM_TYPE", "load_dataset", "load_dataset_with_version"]
