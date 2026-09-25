"""Load an Actor by replaying its stream.

One function. It loads the stream, rebuilds each event, and folds them
into current state. There is no actors table: the answer is recomputed
from history on every call.

That is the right trade for reading one actor by id, where a stream is a
handful of rows. It is the wrong trade for listing or filtering actors,
which cannot replay everybody and needs a maintained summary table
instead. A query of that shape belongs in its own module, not here.

Lives with the aggregate rather than with a slice because it reads the
aggregate's whole stream, whatever command happened to write each row.
"""

from uuid import UUID

from keeper.access.aggregates.actor.events import from_stored
from keeper.access.aggregates.actor.evolver import fold
from keeper.access.aggregates.actor.state import Actor
from keeper.infrastructure.ports.event_store import EventStore

ACTOR_STREAM_TYPE = "Actor"
"""The stream type every Actor event is stored under.

Half of the `(stream_type, event_type)` routing key. Declared as a
constant because the writing side and this reading side must agree on it
and they are in different files.
"""


async def load_actor_with_version(
    event_store: EventStore, actor_id: UUID
) -> tuple[Actor | None, int]:
    """Return the actor's current state and the version it was folded from.

    The version is what a writing handler passes back as
    `expected_version`, so that two callers acting on the same actor at
    once produce one append and one `ConcurrencyError` rather than two
    appends that each believed they were first.

    Reading it here rather than in the handler keeps the rebuild in one
    place: the state and the version it corresponds to come out of the
    same load, and nothing has to re-derive one from the other.
    """
    stored, version = await event_store.load(ACTOR_STREAM_TYPE, actor_id)
    return fold([from_stored(row) for row in stored]), version


async def load_actor(event_store: EventStore, actor_id: UUID) -> Actor | None:
    """Return the actor's current state, or None if the stream is empty.

    An empty stream means no such actor was ever registered. The caller
    decides what that means on its own surface: a 404 over HTTP, an error
    result over MCP.

    For readers. A handler about to append wants
    `load_actor_with_version` instead, because appending without the
    version it read is how a lost update happens.
    """
    state, _version = await load_actor_with_version(event_store, actor_id)
    return state


__all__ = ["ACTOR_STREAM_TYPE", "load_actor", "load_actor_with_version"]
