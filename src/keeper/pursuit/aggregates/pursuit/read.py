"""Load a Pursuit by replaying its stream.

Two loaders, and the difference between them is the version. A handler
about to append to a stream that already has rows needs the version it
folded from, so that two callers acting on one pursuit at once produce one
append and one conflict rather than two rows disagreeing about what
happened.

That version is doing more work here than it does elsewhere, and it is
worth saying why. Nothing claims a pursuit. Two drivers watching one are
expected rather than exceptional, and what keeps them from acting twice is
exactly this: both fold the same state, both append at the same version,
the store lets one through, and the loser reloads and finds the record
already saying what it was about to say. Optimistic concurrency is the
serializer, which is why no lease, no lock and no leader election appears
anywhere in this context.

There is no pursuits table: the answer is recomputed from history on every
call. That is the right trade for reading one pursuit by id, where a stream
is a handful of rows. It is the wrong trade for listing the running ones,
which cannot name a stream and so cannot fold one, and which needs a
maintained summary table instead. Nothing lists them yet.

Lives with the aggregate rather than with a slice because it reads the
aggregate's whole stream, whatever command happened to write each row.
"""

from uuid import UUID

from keeper.infrastructure.ports.event_store import EventStore
from keeper.pursuit.aggregates.pursuit.events import from_stored
from keeper.pursuit.aggregates.pursuit.evolver import fold
from keeper.pursuit.aggregates.pursuit.state import Pursuit

PURSUIT_STREAM_TYPE = "Pursuit"
"""The stream type every Pursuit event is stored under.

Half of the `(stream_type, event_type)` routing key. Declared as a
constant because the writing side and this reading side must agree on it
and they are in different files.
"""


async def load_pursuit(event_store: EventStore, pursuit_id: UUID) -> Pursuit | None:
    """Return the pursuit's current state, or None if the stream is empty.

    An empty stream means no such pursuit was ever started. The caller
    decides what that means on its own surface: a 404 over HTTP, an error
    result over MCP.
    """
    stored, _version = await event_store.load(PURSUIT_STREAM_TYPE, pursuit_id)
    return fold([from_stored(row) for row in stored])


async def load_pursuit_with_version(
    event_store: EventStore, pursuit_id: UUID
) -> tuple[Pursuit | None, int]:
    """Return the pursuit's state and the version it was folded from.

    The version is what a writing handler passes back as `expected_version`,
    and is what makes a driver safe to run more than once. Without it a
    second append would land a transition the decider had no chance to
    refuse, because it decided against state that was already stale.
    """
    stored, version = await event_store.load(PURSUIT_STREAM_TYPE, pursuit_id)
    return fold([from_stored(row) for row in stored]), version


__all__ = ["PURSUIT_STREAM_TYPE", "load_pursuit", "load_pursuit_with_version"]
