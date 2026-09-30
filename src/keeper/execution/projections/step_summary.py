"""Keep `proj_execution_step_summary` in step with what each step produced.

One row per step of every dispatched execution. The sibling projection
holds one row per execution and drops the steps on purpose, because a
page of executions carrying every step would be almost entirely steps.
This is the other half of that trade, and the question it exists for is
the one neither a fold nor that summary can answer: which runs produced
data that nothing recorded where.

## The only projection here that reads two contexts

`dataset_id` comes from Custody's `DatasetRegistered` and every other
column from Execution's own events. Nothing imports across the line: a
subscription names its producer with a string.

The direction was forced rather than preferred. `ExecutionStepDone`
names its step by index, `DatasetRegistered` names it by id, and only
`ExecutionDispatched` holds the pairing, so whichever context holds this
has to subscribe to all three. Custody has no aggregate a step row could
hang from, and giving it one would put Execution's identities behind a
second context's read surface.

What makes it tolerable is that it is derived. An aggregate spanning two
contexts is a coupling nothing can undo; a read model spanning them is a
table that can be dropped and rebuilt from the log, and Execution's
write side stays unable to see a dataset at all.

## Why a row exists for every step

A dispatched step carries its sentence and the operation it cites, and
nothing that says whether driving it will open a run. So the genesis arm
cannot write only the steps that will produce data, and it writes them
all. A step that produced nothing is a row whose `engine_reference`
stays null for the life of the record, which is the same shape the
sibling uses for an execution nothing ever claimed.

The alternative was an arm that deletes rows once a step turns out to
have produced nothing. That needs an arm per outcome, plus one on the
ending for steps never reported, and every one of them has to be
harmless on replay against a row that is already gone. Five arms that
must each be idempotent in the deleting direction, to save rows in a
table whose size is set by how much work a facility does.

## Running twice must be harmless

Delivery is at-least-once and the worker advances its bookmark in the
same transaction as the writes, so a crash between the two replays the
batch. Every statement below is written to leave the table where the
first pass left it: the genesis insert takes `ON CONFLICT DO NOTHING`,
and each update writes the same values it wrote the first time.

The two arms that fill a row do not order themselves against each other.
A dataset may be registered for a step before that step's own ending is
projected, because they are separate streams and nothing sequences them,
so neither arm assumes the other has run. They write different columns
of a row the dispatch already created.
"""

from typing import Any, Final
from uuid import UUID

from keeper.infrastructure.logging import get_logger
from keeper.infrastructure.ports.event_store import StoredEvent
from keeper.infrastructure.projection.subscriber import ConnectionLike

PROJECTION_NAME = "proj_execution_step_summary"
"""The table, the bookmark row, and the registered name.

One constant because the three must match and they are read in three
different places: the migration that creates the table, the worker that
reads the bookmark, and the adapter that queries the rows.
"""

_GENESIS_EVENT_TYPE = "ExecutionDispatched"
_FILED_EVENT_TYPE = "DatasetRegistered"

OUTCOME_EVENT_TYPES: Final[frozenset[str]] = frozenset(
    {
        "ExecutionStepDone",
        "ExecutionStepRefused",
        "ExecutionStepBroken",
        "ExecutionStepSkipped",
    }
)
"""The four events that report one step, whatever the outcome was.

Public because the check that keeps it in step with the aggregate's own
event union reads it, the same way the sibling projection publishes its
own copy of the set.
"""

_OUTCOME_BY_EVENT: Final[dict[str, str]] = {
    "ExecutionStepDone": "Done",
    "ExecutionStepRefused": "Refused",
    "ExecutionStepBroken": "Broken",
    "ExecutionStepSkipped": "Skipped",
}
"""The word each event puts in the row.

Derived from the class name by dropping the prefix everywhere but the
one place the two vocabularies differ, and written out rather than
sliced so that the difference is visible instead of encoded in an
offset.
"""

_INSERT_SQL = f"""
INSERT INTO {PROJECTION_NAME} (
    step_id, execution_id, step_index, describes, beamline, created_at
) VALUES ($1, $2, $3, $4, $5, $6)
ON CONFLICT (step_id) DO NOTHING
"""

_OUTCOME_SQL = f"""
UPDATE {PROJECTION_NAME}
SET outcome = $3, engine_reference = $4, reported_at = $5
WHERE execution_id = $1 AND step_index = $2
"""

_FILED_SQL = f"""
UPDATE {PROJECTION_NAME}
SET dataset_id = $2, filed_at = $3
WHERE step_id = $1
"""
"""Fills the Custody half.

Keyed on the step alone, because that is what a dataset names and it is
unique across every execution. The execution id on the event is not used
to narrow it: a dataset naming one step and a different execution is a
contradiction the write side already refused, and re-checking it here
would turn a bad row into a silent no-op rather than a loud one.

Last writer wins where a run produced more than one dataset, which is
allowed and is the reporting side's policy rather than a rule here. The
column answers whether anything holds this run's output, and for that
question any one of them is as good an answer as another.
"""

_log = get_logger(__name__)


class StepSummaryProjection:
    """Folds execution and dataset events into one row per step."""

    name = PROJECTION_NAME
    subscribed_event_types = frozenset(
        {_GENESIS_EVENT_TYPE, _FILED_EVENT_TYPE, *OUTCOME_EVENT_TYPES}
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
        if event.event_type == _FILED_EVENT_TYPE:
            await self._file(event, conn)
            return
        await self._report(event, conn)

    async def _insert(self, event: StoredEvent, conn: ConnectionLike) -> None:
        """Write one row per dispatched step, with nothing reported yet.

        `execution_id` comes off the envelope rather than the payload, so
        every statement here agrees on which execution a row belongs to
        even if a payload disagrees with its own stream.

        The index is the position in the list, which is what a step
        report names itself by. It is assigned here rather than carried,
        because a dispatched step's payload holds its id and its sentence
        and nothing about where in the list it sits.
        """
        payload: dict[str, Any] = event.payload
        for index, step in enumerate(payload["steps"]):
            await conn.execute(
                _INSERT_SQL,
                UUID(step["id"]),
                event.stream_id,
                index,
                step["describes"],
                payload["beamline"],
                event.occurred_at,
            )

    async def _report(self, event: StoredEvent, conn: ConnectionLike) -> None:
        """Record how one step ended, and what its run was called.

        Only a completion carries a reference, and the others write null
        into that column rather than leaving it alone. They are writing
        what is true: a step that was refused or broken or never reached
        opened no run and named nothing, and a column left alone would
        keep whatever a replay of an earlier event had put there.
        """
        await self._update(
            event,
            conn,
            _OUTCOME_SQL,
            event.stream_id,
            int(event.payload["index"]),
            _OUTCOME_BY_EVENT[event.event_type],
            event.payload.get("engine_reference"),
            event.occurred_at,
        )

    async def _file(self, event: StoredEvent, conn: ConnectionLike) -> None:
        """Record that something holds what this step produced.

        `dataset_id` is the stream id off the envelope, for the reason
        every other id here is: it is what the row and any later
        statement about that dataset would agree on.
        """
        await self._update(
            event,
            conn,
            _FILED_SQL,
            UUID(str(event.payload["step_id"])),
            event.stream_id,
            event.occurred_at,
        )

    async def _update(
        self, event: StoredEvent, conn: ConnectionLike, sql: str, *args: object
    ) -> None:
        """Run one update, or say so when there is no row ahead of it.

        For a step report this cannot happen: an execution's own events
        share a stream and arrive in order, so the dispatch that made the
        row precedes them.

        For a dataset it can, and it is the one case worth a word. A
        dataset may name a step of an execution dispatched before this
        projection existed, whose rows a rebuild has not reached yet. The
        warning names the dataset so an operator can tell that from the
        other reading, which is a dataset naming a step that was never
        dispatched at all.

        Logged rather than raised either way, because raising wedges
        every execution behind one bad row, and the bookmark never moves
        again.
        """
        result = await conn.execute(sql, *args)
        if str(result).endswith(" 0"):
            _log.warning(
                "step_summary.event_without_a_row",
                projection=PROJECTION_NAME,
                stream_id=str(event.stream_id),
                event_type=event.event_type,
                position=event.position,
            )


__all__ = ["OUTCOME_EVENT_TYPES", "PROJECTION_NAME", "StepSummaryProjection"]
