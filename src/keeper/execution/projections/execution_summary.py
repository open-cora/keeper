"""Keep `proj_execution_execution_summary` in step with the execution streams.

## Why this one cannot use a counter

Delivery is at-least-once. The worker advances its bookmark in the same
transaction as the writes, so a crash between the two replays the batch,
and a replayed batch has to leave the table where the first pass left
it.

Every other projection here satisfies that by writing absolute values: a
status derived from the event type is the same value however many times
it is written. Progress through an execution is not a value of that kind. A
column incremented per step would count a replayed step twice, and the
summary would report an execution further along than it is, which is the one
lie a record of an abandoned execution must not tell.

So the row holds the set of indices reported rather than a count of
them, and each step event unions one index into it. A union is
idempotent where an increment is not, and the count a caller reads is
the size of the set. The array is the mechanism; `reported_count` is
what the port exposes.

## The name is three things at once

`proj_execution_execution_summary` is the table, the bookmark row, and this
projection's registered name. They have to agree, because the worker
finds the bookmark by the name and the SQL below finds the table by
spelling it.

## Why the procedure index is not unique

A routine composed once is executed every time it runs, so many rows
under one procedure is the ordinary case rather than a duplicate. The
index exists to make "how has this routine been going" one query, and a
unique constraint on it would refuse the second run of anything.
"""

from typing import Any
from uuid import UUID

from keeper.infrastructure.logging import get_logger
from keeper.infrastructure.ports.event_store import StoredEvent
from keeper.infrastructure.projection.subscriber import ConnectionLike

_log = get_logger(__name__)

PROJECTION_NAME = "proj_execution_execution_summary"
"""The table, the bookmark row, and the registered name.

One constant because the three must match and they are read in three
different places: the migration that creates the table, the worker that
reads the bookmark, and the adapter that queries the rows.
"""

_GENESIS_EVENT_TYPE = "ExecutionDispatched"
_CLAIM_EVENT_TYPE = "ExecutionClaimed"
_ENDING_EVENT_TYPE = "ExecutionEnded"

STEP_EVENT_TYPES = frozenset(
    {"ExecutionStepDone", "ExecutionStepRefused", "ExecutionStepBroken", "ExecutionStepSkipped"}
)
"""The four events that report one step, whatever the outcome was.

Public because the check that keeps it in step with the aggregate's
event union lives in another module. A set only this file can read is a
set only this file can be wrong about.

The summary records that a step was reported and not how it ended. Which
outcome it was is on the event and in the execution's own record; a list view
asking "how far did this get" does not need it, and a column per outcome
would be four columns to keep idempotent instead of one array.
"""

_INSERT_SQL = f"""
INSERT INTO {PROJECTION_NAME} (
    execution_id, procedure_id, procedure_name, beamline,
    step_count, reported_indices, status, created_at, updated_at
) VALUES ($1, $2, $3, $4, $5, '{{}}'::int[], 'Dispatched', $6, $6)
ON CONFLICT (execution_id) DO NOTHING
"""

_CLAIM_SQL = f"""
UPDATE {PROJECTION_NAME}
SET status = 'Claimed', updated_at = GREATEST(updated_at, $2)
WHERE execution_id = $1 AND status = 'Dispatched'
"""
"""Move a dispatched execution to claimed, and leave any other status alone.

The status guard is what makes a replay harmless. Delivery is
at-least-once, so a claim redelivered after the first step report would
otherwise drag a running execution back to claimed, which is a read model
going backwards. Writing an absolute value is not enough here, because
unlike every other status in this tree the order of these two events
matters and a replay does not preserve it.
"""

ENGINE_EVENT_TYPES = frozenset(
    {
        "ExecutionStepEngineStarted",
        "ExecutionStepEnginePaused",
        "ExecutionStepEngineResumed",
        "ExecutionStepEngineCompleted",
        "ExecutionStepEngineAborted",
        "ExecutionStepEngineFailed",
    }
)
"""The six events relaying what an engine did to one step's run.

Subscribed, although no column here holds an engine state. The fold moves
an execution to `Running` on any of them, because an engine that opened a run
for one of its steps is evidence something is driving it, and a summary
that did not would disagree with the aggregate. That divergence is
exactly what the shared port-contract suite exists to catch, and it would
have caught this one.

They do NOT touch `reported_indices`. That set counts what the DRIVER
reported, which is how far the execution got; an engine's account of one run
is a different question and adding to it would inflate the progress of a
execution whose driver has said nothing.
"""

_ENGINE_SQL = f"""
UPDATE {PROJECTION_NAME}
SET status = CASE WHEN status = 'Ended' THEN status ELSE 'Running' END,
    updated_at = GREATEST(updated_at, $2)
WHERE execution_id = $1
"""
"""Move a live execution to running on any engine report.

Same replay guard the step statement carries, for the same reason: a
report redelivered after the execution ended would otherwise reopen it.
"""

_STEP_SQL = f"""
UPDATE {PROJECTION_NAME}
SET reported_indices = (
        SELECT array_agg(DISTINCT index ORDER BY index)
        FROM unnest(reported_indices || $2::int) AS index
    ),
    status = CASE WHEN status = 'Ended' THEN status ELSE 'Running' END,
    updated_at = GREATEST(updated_at, $3)
WHERE execution_id = $1
"""
"""Union one index in, and move a live execution to running.

The `CASE` is the same replay guard the claim statement carries, for the
opposite direction: a step redelivered after the execution ended would
otherwise reopen it.
"""

_END_SQL = f"""
UPDATE {PROJECTION_NAME}
SET status = 'Ended', updated_at = GREATEST(updated_at, $2)
WHERE execution_id = $1
"""
"""Close the execution. No guard, because ended is terminal and absolute."""


class ExecutionSummaryProjection:
    """Folds execution events into one row per execution."""

    name = PROJECTION_NAME
    subscribed_event_types = frozenset(
        {
            _GENESIS_EVENT_TYPE,
            _CLAIM_EVENT_TYPE,
            _ENDING_EVENT_TYPE,
            *STEP_EVENT_TYPES,
            *ENGINE_EVENT_TYPES,
        },
    )

    async def apply(self, event: StoredEvent, conn: ConnectionLike) -> None:
        """Write one event into the table, inside the worker's transaction.

        Raising rolls the whole batch back and leaves the bookmark where
        it was, so an event this cannot handle is retried forever rather
        than skipped. That is the right failure for a read model: stale
        and loud beats wrong and quiet.
        """
        if event.event_type == _GENESIS_EVENT_TYPE:
            await self._insert(event, conn)
            return
        if event.event_type in ENGINE_EVENT_TYPES:
            await self._apply(event, conn, _ENGINE_SQL, event.stream_id, event.occurred_at)
            return
        if event.event_type == _CLAIM_EVENT_TYPE:
            await self._apply(event, conn, _CLAIM_SQL, event.stream_id, event.occurred_at)
            return
        if event.event_type == _ENDING_EVENT_TYPE:
            await self._apply(event, conn, _END_SQL, event.stream_id, event.occurred_at)
            return
        await self._apply(
            event,
            conn,
            _STEP_SQL,
            event.stream_id,
            int(event.payload["index"]),
            event.occurred_at,
        )

    async def _insert(self, event: StoredEvent, conn: ConnectionLike) -> None:
        """Write the genesis row, with no step reported yet.

        `execution_id` comes off the envelope rather than the payload: the
        stream id is what every statement here agrees on, and reading it
        from the payload would let a malformed row point one statement
        at a different execution than the other.

        `step_count` is stored rather than derived, because the list it
        counts is not in this table. It cannot change afterwards: no
        command adds a step to an execution.
        """
        payload: dict[str, Any] = event.payload
        await conn.execute(
            _INSERT_SQL,
            event.stream_id,
            UUID(payload["procedure_id"]),
            payload["procedure_name"],
            payload["beamline"],
            len(payload["steps"]),
            event.occurred_at,
        )

    async def _apply(
        self, event: StoredEvent, conn: ConnectionLike, sql: str, *args: object
    ) -> None:
        """Run one update, or say so when there is no row ahead of it.

        A step or an ending with no row means the genesis is missing,
        which the ordering guarantees cannot happen: events arrive in
        `(transaction_id, position)` order and an execution's own events share
        a stream. It is logged rather than raised because the
        alternative is wedging the whole projection over one execution, and a
        warning naming the execution is what an operator needs to rebuild it.
        """
        result = await conn.execute(sql, *args)
        if str(result).endswith(" 0"):
            _log.warning(
                "execution_summary.event_without_a_row",
                projection=PROJECTION_NAME,
                execution_id=str(event.stream_id),
                event_type=event.event_type,
                position=event.position,
            )


__all__ = ["PROJECTION_NAME", "STEP_EVENT_TYPES", "ExecutionSummaryProjection"]
