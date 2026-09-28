"""Load an Operation by replaying its stream.

One function. It loads the stream, rebuilds each event, and folds them
into current state. There is no operations table: the answer is recomputed
from history on every call.

That is the right trade for reading one operation by id, where a stream is a
single row today and a handful once an operation can be retired. It is the
wrong trade for listing or filtering operations, which cannot replay
everything and needs a maintained summary table instead. A query of that
shape belongs in its own module, not here.

Nothing here hands back the version the state was folded from, and the
sibling loader that would is absent on purpose. That version is what a
writing handler passes as its expected version so two callers acting at
once produce one append and one conflict, and it matters only where a
handler appends to a stream that already has rows. Nothing appends to a
operation after its genesis, so the loader that returns it arrives with the
first command that does.

Lives with the aggregate rather than with a slice because it reads the
aggregate's whole stream, whatever command happened to write each row.
"""

from uuid import UUID

from keeper.execution.aggregates.operation.events import from_stored
from keeper.execution.aggregates.operation.evolver import fold
from keeper.execution.aggregates.operation.state import Operation
from keeper.infrastructure.ports.event_store import EventStore

OPERATION_STREAM_TYPE = "Operation"
"""The stream type every Operation event is stored under.

Half of the `(stream_type, event_type)` routing key. Declared as a
constant because the writing side and this reading side must agree on it
and they are in different files.
"""


async def load_operation(event_store: EventStore, operation_id: UUID) -> Operation | None:
    """Return the operation's current state, or None if the stream is empty.

    An empty stream means no such operation was ever defined. The caller
    decides what that means on its own surface: a 404 over HTTP, an error
    result over MCP.
    """
    stored, _version = await event_store.load(OPERATION_STREAM_TYPE, operation_id)
    return fold([from_stored(row) for row in stored])


__all__ = ["OPERATION_STREAM_TYPE", "load_operation"]
