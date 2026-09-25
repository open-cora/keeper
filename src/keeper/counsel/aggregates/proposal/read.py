"""Load a Proposal by replaying its stream.

Two loaders, and the difference between them is the version. A handler
about to append to a stream that already has rows needs the version it
folded from, so that two callers taking the same proposal at once
produce one append and one conflict rather than two runs recorded
against one proposal. A reader needs no such thing and gets the shorter
function.

Custody has only the shorter one, because nothing appends to a dataset
after its genesis. This aggregate has a second command, so both are
here from the first landing.

There is no proposals table: the answer is recomputed from history on
every call. That is the right trade for reading one proposal by id,
where a stream is one row or two. It is the wrong trade for finding the
open ones, which cannot name a stream and so cannot fold one, and which
needs a maintained summary table instead. That belongs in its own module
and is not here yet.

Lives with the aggregate rather than with a slice because it reads the
aggregate's whole stream, whatever command happened to write each row.
"""

from uuid import UUID

from keeper.counsel.aggregates.proposal.events import from_stored
from keeper.counsel.aggregates.proposal.evolver import fold
from keeper.counsel.aggregates.proposal.state import Proposal
from keeper.infrastructure.ports.event_store import EventStore

PROPOSAL_STREAM_TYPE = "Proposal"
"""The stream type every Proposal event is stored under.

Half of the `(stream_type, event_type)` routing key. Declared as a
constant because the writing side and this reading side must agree on it
and they are in different files.
"""


async def load_proposal(event_store: EventStore, proposal_id: UUID) -> Proposal | None:
    """Return the proposal's current state, or None if the stream is empty.

    An empty stream means no such proposal was ever made. The caller
    decides what that means on its own surface: a 404 over HTTP, an error
    result over MCP.
    """
    stored, _version = await event_store.load(PROPOSAL_STREAM_TYPE, proposal_id)
    return fold([from_stored(row) for row in stored])


async def load_proposal_with_version(
    event_store: EventStore, proposal_id: UUID
) -> tuple[Proposal | None, int]:
    """Return the proposal's state and the version it was folded from.

    The version is what a writing handler passes back as
    `expected_version`, so that two callers taking one proposal at once
    produce one append and one `ConcurrencyError`. Without it the second
    append would land a second run against a proposal that already had
    one, which the decider exists to refuse.
    """
    stored, version = await event_store.load(PROPOSAL_STREAM_TYPE, proposal_id)
    return fold([from_stored(row) for row in stored]), version


__all__ = ["PROPOSAL_STREAM_TYPE", "load_proposal", "load_proposal_with_version"]
