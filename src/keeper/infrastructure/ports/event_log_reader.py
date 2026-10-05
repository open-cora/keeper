"""EventLogReader port: read the whole log in commit order.

`EventStore` answers "what happened to this stream". This answers "what
happened", in the order it committed, from a position the caller holds.
Two capabilities and two Protocols, because an implementation satisfying
one has no business offering the other: a caller tailing the log must not
be handed `append`, and `InMemoryEventStore.stream_ids` already states the
converse, that a port method loading everything of a kind is an invitation.

## The cursor is a pair, and a bare position is a bug

`position` is a `bigserial`, allocated before commit, so a reader paging on
it alone can step over a row whose transaction has not committed yet and
never come back for it. The cursor is therefore `(transaction_id, position)`
and the read excludes transactions still in flight. `keeper.infrastructure
.ports.event_store` carries the long form of the argument, and the
projection worker advances the same way against the same index.

A reader starting from nothing passes `LogCursor.BEGINNING`, whose zero
transaction id compares strictly less than any real one, which is the
sentinel the projection bookmarks already use.

## Why the filter is an allow list

`stream_types` names what the caller may see rather than what it may not.
An aggregate arriving later is then invisible until somebody names it,
which is the safe direction: the alternative shows a new stream to every
existing reader on the day it is added, and nothing would say so.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import ClassVar, Protocol

from keeper.infrastructure.ports.event_store import StoredEvent


@dataclass(frozen=True)
class LogCursor:
    """Where a reader of the log has got to.

    Ordered lexicographically, which is how the read compares it: one
    transaction may carry several events with distinct positions, and the
    pair keeps them in order without splitting the transaction.
    """

    transaction_id: int
    position: int

    BEGINNING: ClassVar["LogCursor"]
    """The cursor a reader with no history passes.

    Zero rather than None so the comparison in every implementation stays
    one shape. The projection bookmarks use the same sentinel.
    """


LogCursor.BEGINNING = LogCursor(transaction_id=0, position=0)


@dataclass(frozen=True)
class LogPage:
    """One page of the log, and where to carry on from.

    `next_cursor` is None when the page is empty, so a caller that got
    nothing keeps the cursor it already held rather than being handed a
    position it cannot distinguish from where it started.
    """

    items: Sequence[StoredEvent]
    next_cursor: LogCursor | None


class EventLogReader(Protocol):
    """Read committed events in commit order, from a cursor."""

    async def read_after(
        self,
        cursor: LogCursor,
        *,
        limit: int,
        stream_types: Sequence[str],
    ) -> LogPage:
        """Up to `limit` committed events after `cursor`, oldest first.

        Only events whose `stream_type` is in `stream_types` are returned,
        and an empty sequence therefore returns an empty page rather than
        everything. Events from transactions still in flight are never
        returned, which is what makes the cursor safe to persist.
        """
        ...


__all__ = ["EventLogReader", "LogCursor", "LogPage"]
