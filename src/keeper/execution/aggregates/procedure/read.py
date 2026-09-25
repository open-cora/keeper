"""Load a Procedure by replaying its stream.

One function. It loads the stream, rebuilds each event, and folds them
into current state. There is no procedures table: the answer is
recomputed from history on every call.

That is the right trade for reading one procedure by id, where a stream
is a single row today and a handful once a procedure can be retired. It
is the wrong trade for listing or filtering procedures, which cannot
replay everything and needs a maintained summary table instead. A query
of that shape belongs in its own module, not here.

Nothing here hands back the version the state was folded from, and the
sibling loader that would is absent on purpose. That version is what a
writing handler passes as its expected version so two callers acting at
once produce one append and one conflict, and it matters only where a
handler appends to a stream that already has rows. Nothing appends to a
procedure after its genesis, so the loader that returns it arrives with
the first command that does.

Lives with the aggregate rather than with a slice because it reads the
aggregate's whole stream, whatever command happened to write each row.
"""

from uuid import UUID

from keeper.execution.aggregates.procedure.events import from_stored
from keeper.execution.aggregates.procedure.evolver import fold
from keeper.execution.aggregates.procedure.state import Procedure
from keeper.infrastructure.ports.event_store import EventStore

PROCEDURE_STREAM_TYPE = "Procedure"
"""The stream type every Procedure event is stored under.

Half of the `(stream_type, event_type)` routing key. Declared as a
constant because the writing side and this reading side must agree on it
and they are in different files.
"""


async def load_procedure(event_store: EventStore, procedure_id: UUID) -> Procedure | None:
    """Return the procedure's current state, or None if the stream is empty.

    An empty stream means no such procedure was ever defined. The caller
    decides what that means on its own surface: a 404 over HTTP, an error
    result over MCP.
    """
    stored, _version = await event_store.load(PROCEDURE_STREAM_TYPE, procedure_id)
    return fold([from_stored(row) for row in stored])


__all__ = ["PROCEDURE_STREAM_TYPE", "load_procedure"]
