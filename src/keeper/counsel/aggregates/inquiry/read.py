"""Load an Inquiry by replaying its stream.

Two loaders, and the difference between them is the version. A handler
about to append to a stream that already has rows needs the version it
folded from, so that two thinkers answering one question at once produce one
append and one conflict rather than two conclusions against one asking. A
reader needs no such thing and gets the shorter function.

There is no inquiries table: the answer is recomputed from history on every
call. That is the right trade for reading one inquiry by id, where a stream
is one row to three. It is the wrong trade for finding the open ones, which
cannot name a stream and so cannot fold one, and which needs the maintained
summary table beside this module instead.

Lives with the aggregate rather than with a slice because it reads the
aggregate's whole stream, whatever command happened to write each row.
"""

from uuid import UUID

from keeper.counsel.aggregates.inquiry.events import from_stored
from keeper.counsel.aggregates.inquiry.evolver import fold
from keeper.counsel.aggregates.inquiry.state import Inquiry
from keeper.infrastructure.ports.event_store import EventStore

INQUIRY_STREAM_TYPE = "Inquiry"
"""The stream type every Inquiry event is stored under.

Half of the `(stream_type, event_type)` routing key. Declared as a constant
because the writing side and this reading side must agree on it and they are
in different files.
"""


async def load_inquiry(event_store: EventStore, inquiry_id: UUID) -> Inquiry | None:
    """Return the inquiry's current state, or None if the stream is empty.

    An empty stream means no such question was ever put. The caller decides
    what that means on its own surface: a 404 over HTTP, an error result
    over MCP.
    """
    stored, _version = await event_store.load(INQUIRY_STREAM_TYPE, inquiry_id)
    return fold([from_stored(row) for row in stored])


async def load_inquiry_with_version(
    event_store: EventStore, inquiry_id: UUID
) -> tuple[Inquiry | None, int]:
    """Return the inquiry's state and the version it was folded from.

    The version is what a writing handler passes back as `expected_version`,
    so that two thinkers answering one question at once produce one append
    and one `ConcurrencyError`. Without it the second append would land a
    second conclusion against an inquiry that already had one, which the
    decider exists to refuse.
    """
    stored, version = await event_store.load(INQUIRY_STREAM_TYPE, inquiry_id)
    return fold([from_stored(row) for row in stored]), version


__all__ = ["INQUIRY_STREAM_TYPE", "load_inquiry", "load_inquiry_with_version"]
