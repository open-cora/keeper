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

Nothing here hands back the version the state was folded from, and the
sibling loader that would is absent on purpose. That version is what a
writing handler passes as its expected version so two callers acting at
once produce one append and one conflict, and it matters only where a
handler appends to a stream that already has rows. Nothing appends to a
dataset after its genesis, so the loader that returns it arrives with the
first command that does.

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


__all__ = ["DATASET_STREAM_TYPE", "load_dataset"]
