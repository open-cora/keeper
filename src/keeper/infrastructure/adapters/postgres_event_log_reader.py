"""Postgres `EventLogReader`: the committed log, in commit order, by page.

One query against `events`, advancing on the `(transaction_id, position)`
pair over `events_advance_idx` and excluding transactions still in flight.
That is the same advance the projection worker makes, for the same reason,
and `keeper.infrastructure.ports.event_log_reader` states it once.

The filter is on `stream_type` rather than on `event_type`, which is what
separates this from the worker's query: a subscriber knows the handful of
events it folds, and a reader of the log wants whole aggregates or none of
them. Both are an `ANY` against the same index, so the plan is the same
shape.

This reader never writes and never loads a stream, so a deployment hands
it to the log route and hands `PostgresEventStore` to everything else.
Both wrap the same pool.

The xid8 goes in as a Python int and comes back as text. That asymmetry
is the driver's and not a choice here: asyncpg accepts an int for an
`$1::xid8` parameter and ships no output codec for the type, so the
SELECT casts it and the row mapper parses it. Passing the cursor's
transaction id as a string instead is refused by the driver before the
query runs, rather than answering wrongly, which is the one mercy in it.
"""

# asyncpg ships no type information for Pool.acquire / Connection.fetch, so
# pyright resolves the single call below to Unknown.
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false

from collections.abc import Sequence

import asyncpg

from keeper.infrastructure.adapters.postgres_event_store import row_to_stored_event
from keeper.infrastructure.ports.event_log_reader import LogCursor, LogPage

_READ_AFTER_SQL = """
SELECT position, event_id, stream_type, stream_id, version, event_type,
       schema_version, payload, metadata, correlation_id, causation_id,
       principal_id, occurred_at, recorded_at,
       transaction_id::text AS transaction_id_text
FROM events
WHERE (transaction_id, position) > ($1::xid8, $2)
  AND transaction_id < pg_snapshot_xmin(pg_current_snapshot())
  AND stream_type = ANY($3::text[])
ORDER BY transaction_id ASC, position ASC
LIMIT $4
"""


class PostgresEventLogReader:
    """Read the event log from a cursor, over an asyncpg pool."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def read_after(
        self,
        cursor: LogCursor,
        *,
        limit: int,
        stream_types: Sequence[str],
    ) -> LogPage:
        """Up to `limit` committed events after `cursor`, oldest first.

        An empty `stream_types` returns an empty page without a query.
        Postgres would answer the same way, and spending a round trip to
        be told so is a cost the caller's own filter already decided.
        """
        wanted = list(stream_types)
        if not wanted or limit <= 0:
            return LogPage(items=[], next_cursor=None)

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                _READ_AFTER_SQL,
                cursor.transaction_id,
                cursor.position,
                wanted,
                limit,
            )
        if not rows:
            return LogPage(items=[], next_cursor=None)

        events = [row_to_stored_event(row) for row in rows]
        last = events[-1]
        return LogPage(
            items=events,
            next_cursor=LogCursor(transaction_id=last.transaction_id, position=last.position),
        )


__all__ = ["PostgresEventLogReader"]
