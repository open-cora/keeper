"""Keep `proj_custody_dataset_summary` in step with the dataset streams.

Three subscribed event types and three arms: a dataset appears, gains an
address, and loses one. No transitions and no derived status, because
the only thing that changes about a dataset is where its data can be
reached.

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

`ON CONFLICT (dataset_id) DO NOTHING` covers the genesis arm, and the
other two are written so that applying them twice is applying them
once. Adding an address tests for it first, and removing one filters
the array rather than taking a position out of it, so neither depends
on how many times the batch arrived.

That is why addresses are kept as a set in a column rather than as
rows counted somewhere. A counter would have to be exactly right about
delivery; a set only has to be right about membership.

An update that matches no row raises, because a replication arriving
before the registration it belongs to means the worker read the log out
of order, and that is a real fault rather than a row to skip. Letting
it pass would leave a dataset listed at an address the log says it also
has, which is the quiet wrongness this projection would rather crash
than ship.

## What a duplicated reference does

Nothing, and for the same reason the sibling declined the same index. Two
records naming one address make two rows and a caller sees both. A unique
index would enforce uniqueness by dropping the second row here, leaving a
dataset that exists in the log missing from every listing, and a read
model that undercounts is worse than one that shows the caller the
duplicate. The guard against a redelivered report is the idempotency key
on the write path, which acts before an event exists at all.

That is about two datasets naming one address. One dataset naming one
address twice is a different thing and cannot happen: the write path
refuses it, and the arm below would ignore it anyway.
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
_REPLICATED_EVENT_TYPE = "DatasetReplicated"
_WITHDRAWN_EVENT_TYPE = "DatasetWithdrawn"

_INSERT_SQL = f"""
INSERT INTO {PROJECTION_NAME} (
    dataset_id, execution_id, step_id, external_refs, created_at
) VALUES ($1, $2, $3, jsonb_build_array($4::jsonb), $5)
ON CONFLICT (dataset_id) DO NOTHING
"""

_ADD_REF_SQL = f"""
UPDATE {PROJECTION_NAME}
SET external_refs = CASE
    WHEN external_refs @> jsonb_build_array($2::jsonb) THEN external_refs
    ELSE external_refs || jsonb_build_array($2::jsonb)
END
WHERE dataset_id = $1
"""

_DROP_REF_SQL = f"""
UPDATE {PROJECTION_NAME}
SET external_refs = COALESCE(
    (
        SELECT jsonb_agg(held)
        FROM jsonb_array_elements(external_refs) AS held
        WHERE held <> $2::jsonb
    ),
    '[]'::jsonb
)
WHERE dataset_id = $1
"""


class MissingDatasetRowError(RuntimeError):
    """An address changed on a dataset this table has never heard of."""

    def __init__(self, dataset_id: UUID, event_type: str) -> None:
        super().__init__(
            f"{event_type} names dataset {dataset_id}, which has no row here, so the "
            "log was read out of order"
        )
        self.dataset_id = dataset_id
        self.event_type = event_type


class DatasetSummaryProjection:
    """Folds dataset events into one row per dataset."""

    name = PROJECTION_NAME
    subscribed_event_types = frozenset(
        {_GENESIS_EVENT_TYPE, _REPLICATED_EVENT_TYPE, _WITHDRAWN_EVENT_TYPE}
    )

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
        reference = _reference(payload)
        if event.event_type == _GENESIS_EVENT_TYPE:
            await conn.execute(
                _INSERT_SQL,
                event.stream_id,
                UUID(payload["execution_id"]),
                UUID(payload["step_id"]),
                reference,
                event.occurred_at,
            )
            return
        statement = _ADD_REF_SQL if event.event_type == _REPLICATED_EVENT_TYPE else _DROP_REF_SQL
        changed = await conn.execute(statement, event.stream_id, reference)
        _refuse_a_row_that_was_not_there(changed, event.stream_id, event.event_type)


def _reference(payload: dict[str, Any]) -> dict[str, str]:
    """The address as one object, so the column holds pairs not halves.

    The same shape in all three statements, which is what lets the
    removing arm compare whole references rather than two columns that
    could match one apiece.
    """
    return {"scheme": payload["external_ref_scheme"], "value": payload["external_ref_value"]}


def _refuse_a_row_that_was_not_there(changed: object, dataset_id: UUID, event_type: str) -> None:
    """Raise unless the update found the dataset it names.

    asyncpg reports an update as a tag counting the rows it touched, and
    a zero there means the genesis row is missing. Retried forever is
    the right failure: the row either appears when the earlier event is
    replayed, or somebody looks at why it never does.
    """
    if str(changed).strip().rsplit(" ", 1)[-1] == "0":
        raise MissingDatasetRowError(dataset_id, event_type)


__all__ = ["PROJECTION_NAME", "DatasetSummaryProjection", "MissingDatasetRowError"]
