"""Keep `proj_execution_operation_summary` in step with the operation streams.

The Execution projection's sibling, and much the smaller of the two,
because an operation has one event. There are no transitions to fold, so
there is no status table and no update statement: an operation stream is
a single row that arrives once and never moves.

That makes idempotency easy rather than absent. `ON CONFLICT (operation_id) DO
NOTHING` is what makes a replayed batch harmless, and it is load-bearing
even here: delivery is at-least-once and the same genesis will arrive
twice sooner or later.

## The name is three things at once

`proj_execution_operation_summary` is the table, the bookmark row, and this
projection's registered name. `test_projections_have_a_table_and_a_bookmark.py`
is what makes the agreement a rule rather than a habit.

## Two operations may share a name and both rows stay

There is no unique index on the name, deliberately, because the aggregate
says two operations may carry one name on purpose. A unique index here would
drop the second, which would hide an operation that exists in the log from
every listing and from the caller most likely to be confused by it.
"""

from typing import Any

from keeper.infrastructure.ports.event_store import StoredEvent
from keeper.infrastructure.projection.subscriber import ConnectionLike

PROJECTION_NAME = "proj_execution_operation_summary"
"""The table, the bookmark row, and the registered name.

One constant because the three must match and they are read in three
different places: the migration that creates the table, the worker that
reads the bookmark, and the adapter that queries the rows.
"""

_GENESIS_EVENT_TYPE = "OperationDefined"

_INSERT_SQL = f"""
INSERT INTO {PROJECTION_NAME} (operation_id, name, created_at)
VALUES ($1, $2, $3)
ON CONFLICT (operation_id) DO NOTHING
"""


class OperationSummaryProjection:
    """Folds operation events into one row per operation."""

    name = PROJECTION_NAME
    subscribed_event_types = frozenset({_GENESIS_EVENT_TYPE})

    async def apply(self, event: StoredEvent, conn: ConnectionLike) -> None:
        """Write one operation into the table, inside the worker's transaction.

        No branch, because there is one event type and the subscription
        names it. A second operation event subscribed to without a branch
        added here would reach this statement and fail looking for a key
        its payload does not carry, which wedges the projection loudly
        rather than writing a wrong row quietly. That is the right way
        round for a read model.
        """
        payload: dict[str, Any] = event.payload
        await conn.execute(
            _INSERT_SQL,
            event.stream_id,
            payload["operation_name"],
            event.occurred_at,
        )


__all__ = ["PROJECTION_NAME", "OperationSummaryProjection"]
