"""Load a Policy by replaying its stream.

There is no policies table. A policy's current state is recomputed from
history every time it is read.

That is the right trade here for the same reason it is right for an
actor, and for one more: the authorization adapter reads the active
policy on every request, so the cost is paid per call. A stream that is
a handful of rows is cheaper to fold than a projection is to maintain
and invalidate. When a policy grows past that, the answer is a cache
with an invalidation story, not a summary table added ahead of the need.
"""

from uuid import UUID

from keeper.authority.aggregates.policy.events import from_stored
from keeper.authority.aggregates.policy.evolver import fold
from keeper.authority.aggregates.policy.state import Policy
from keeper.infrastructure.ports.event_store import EventStore

POLICY_STREAM_TYPE = "Policy"
"""The stream type every Policy event is stored under.

Half of the `(stream_type, event_type)` routing key. Declared as a
constant because the writing side and this reading side must agree on
it and they are in different files.
"""


async def load_policy_with_version(
    event_store: EventStore, policy_id: UUID
) -> tuple[Policy | None, int]:
    """Return the policy's current state and the version it was folded from.

    The version is what a writing handler passes back as
    `expected_version`, so two callers editing the same policy at once
    produce one append and one `ConcurrencyError` rather than two
    appends that each believed they were first.
    """
    stored, version = await event_store.load(POLICY_STREAM_TYPE, policy_id)
    return fold([from_stored(row) for row in stored]), version


async def load_policy(event_store: EventStore, policy_id: UUID) -> Policy | None:
    """Return the policy's current state, or None if the stream is empty.

    For readers, the authorization adapter among them. A handler about
    to append wants `load_policy_with_version` instead, because
    appending without the version it read is how a lost update happens.
    """
    state, _version = await load_policy_with_version(event_store, policy_id)
    return state
