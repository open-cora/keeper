"""Keep `proj_custody_dataset_summary` in step with the dataset streams.

The simplest projection in the tree, and worth reading for that: one
subscribed event type, one INSERT, no transitions and no derived status.
A context whose aggregate has a single event has a projection with a
single arm, and nothing here has to decide anything.

## The name is three things at once

`proj_custody_dataset_summary` is the table, the bookmark row, and this
projection's registered name. They have to agree, because the worker finds
the bookmark by the name and the SQL below finds the table by spelling it,
and `test_projections_have_a_table_and_a_bookmark.py` is what makes the
agreement a rule rather than a habit.

## Running twice must be harmless

Delivery is at-least-once. The worker advances its bookmark in the same
transaction as the writes, so a crash between the two replays the batch,
and a replayed batch has to leave the table where the first pass left it.

`ON CONFLICT (dataset_id) DO NOTHING` is the whole of it. With one event
per stream there is no later write that could overwrite an earlier
column, which is the hazard the sibling projection has to keep in mind
for `created_at`. That hazard arrives here with the first event that
changes a dataset, and the arm that handles it will need the same care.

## What a duplicated reference does

Nothing, and for the same reason the sibling declined the same index. Two
records naming one address make two rows and a caller sees both. A unique
index would enforce uniqueness by dropping the second row here, leaving a
dataset that exists in the log missing from every listing, and a read
model that undercounts is worse than one that shows the caller the
duplicate. The guard against a redelivered report is the idempotency key
on the write path, which acts before an event exists at all.
"""

from typing import Any
from uuid import UUID

from keeper.infrastructure.ports.event_store import StoredEvent
from keeper.infrastructure.projection.subscriber import ConnectionLike

PROJECTION_NAME = "proj_custody_dataset_summary"
"""The table, the bookmark row, and the registered name.

One constant because the three must match and they are read in three
different places: the migration that creates the table, the worker that
reads the bookmark, and the adapter that queries the rows.
"""

_GENESIS_EVENT_TYPE = "DatasetRegistered"

_INSERT_SQL = f"""
INSERT INTO {PROJECTION_NAME} (
    dataset_id, execution_id, step_id, external_ref_scheme, external_ref_value, created_at
) VALUES ($1, $2, $3, $4, $5, $6)
ON CONFLICT (dataset_id) DO NOTHING
"""


class DatasetSummaryProjection:
    """Folds dataset events into one row per dataset."""

    name = PROJECTION_NAME
    subscribed_event_types = frozenset({_GENESIS_EVENT_TYPE})

    async def apply(self, event: StoredEvent, conn: ConnectionLike) -> None:
        """Write one event into the table, inside the worker's transaction.

        Raising rolls the whole batch back and leaves the bookmark where
        it was, so an event this cannot handle is retried forever rather
        than skipped. That is the right failure for a read model: stale
        and loud beats wrong and quiet.

        `dataset_id` comes off the envelope rather than the payload,
        because the stream id is what the table's primary key and any
        later statement would agree on, and reading it from the payload
        would let a malformed row point two statements at different
        datasets. The execution and step ids have no such second source
        and are parsed back out of the payload, where they are strings
        because payloads hold primitives.
        """
        payload: dict[str, Any] = event.payload
        await conn.execute(
            _INSERT_SQL,
            event.stream_id,
            UUID(payload["execution_id"]),
            UUID(payload["step_id"]),
            payload["external_ref_scheme"],
            payload["external_ref_value"],
            event.occurred_at,
        )


__all__ = ["PROJECTION_NAME", "DatasetSummaryProjection"]
