"""Keep `proj_counsel_proposal_summary` in step with the proposal streams.

Two arms, one per event, which is the middle of the three projections in
this tree: simpler than an execution's, which maps many event types onto
a status and a set, and less trivial than a dataset's, which has one
INSERT and no transitions.

## The name is three things at once

`proj_counsel_proposal_summary` is the table, the bookmark row, and this
projection's registered name. They have to agree, because the worker
finds the bookmark by the name and the SQL below finds the table by
spelling it, and `test_projections_have_a_table_and_a_bookmark.py` is
what makes the agreement a rule rather than a habit.

## Running twice must be harmless

Delivery is at-least-once. The worker advances its bookmark in the same
transaction as the writes, so a crash between the two replays the batch,
and a replayed batch has to leave the table where the first pass left it.

The genesis takes `ON CONFLICT (proposal_id) DO NOTHING`. The take is
idempotent for a different reason and it is worth being explicit: it
writes the same two values every time, derived entirely from the event
rather than from what the row currently holds, so applying it twice is
applying it once. A projection arm that incremented or appended could not
say that.

## Why the update is not conditional

The take writes the step reference and `taken_at` over whatever is
there, without checking that the row is still open. The decider already refuses a second
take, so a stream carrying two is a stream that could not have been
written, and an arm defending against it would be defending against a
state the write side makes impossible.

What the arm does handle is the row not being there at all. That means
the genesis is missing, which the ordering guarantees cannot happen:
events arrive in `(transaction_id, position)` order and a proposal's own
events share a stream. It is logged rather than raised, because the
alternative is wedging the whole projection over one proposal, and a
warning naming it is what an operator needs to rebuild.

## Why there is no status column

The table stores the step reference nullable and nothing else. Openness
is the null test, on the read side and here, so there is no second
spelling of one bit for these two arms to write inconsistently.
"""

from typing import Any
from uuid import UUID

from keeper.infrastructure.logging import get_logger
from keeper.infrastructure.ports.event_store import StoredEvent
from keeper.infrastructure.projection.subscriber import ConnectionLike

PROJECTION_NAME = "proj_counsel_proposal_summary"
"""The table, the bookmark row, and the registered name.

One constant because the three must match and they are read in three
different places: the migration that creates the table, the worker that
reads the bookmark, and the adapter that queries the rows.
"""

_GENESIS_EVENT_TYPE = "ProposalMade"
_TAKEN_EVENT_TYPE = "ProposalTaken"

_INSERT_SQL = f"""
INSERT INTO {PROJECTION_NAME} (
    proposal_id, actor_id, plan_id, execution_id, step_id, created_at, taken_at
) VALUES ($1, $2, $3, NULL, NULL, $4, NULL)
ON CONFLICT (proposal_id) DO NOTHING
"""

_TAKE_SQL = f"""
UPDATE {PROJECTION_NAME}
SET execution_id = $2, step_id = $3, taken_at = $4
WHERE proposal_id = $1
"""

_log = get_logger(__name__)


class ProposalSummaryProjection:
    """Folds proposal events into one row per proposal."""

    name = PROJECTION_NAME
    subscribed_event_types = frozenset({_GENESIS_EVENT_TYPE, _TAKEN_EVENT_TYPE})

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
        await self._take(event, conn)

    async def _insert(self, event: StoredEvent, conn: ConnectionLike) -> None:
        """Write the genesis row, open.

        `actor_id` and `plan_id` are parsed back into UUIDs because a
        payload holds primitives and the columns hold uuids.
        `proposal_id` comes off the envelope rather than the payload: the
        stream id is what both statements here agree on, and reading it
        from the payload would let a malformed row point one statement at
        a different proposal than the other.

        `created_at` is the envelope's domain time, which for this event
        is this system's own clock reading, because making a proposal is
        an act performed here rather than one reported to it.
        """
        payload: dict[str, Any] = event.payload
        await conn.execute(
            _INSERT_SQL,
            event.stream_id,
            UUID(payload["actor_id"]),
            UUID(payload["plan_id"]),
            event.occurred_at,
        )

    async def _take(self, event: StoredEvent, conn: ConnectionLike) -> None:
        """Put the acquisition on an existing row, or say so when there is none.

        `taken_at` is the envelope's domain time, which for this event
        may be a caller's claim rather than a clock reading, because the
        step was driven somewhere else. Two timestamps on one row from
        two authorities is R8 reaching the read side.
        """
        payload: dict[str, Any] = event.payload
        result = await conn.execute(
            _TAKE_SQL,
            event.stream_id,
            UUID(payload["execution_id"]),
            UUID(payload["step_id"]),
            event.occurred_at,
        )
        if isinstance(result, str) and result.endswith(" 0"):
            _log.warning(
                "proposal_summary.take_without_row",
                projection=PROJECTION_NAME,
                proposal_id=str(event.stream_id),
                position=event.position,
            )


__all__ = ["PROJECTION_NAME", "ProposalSummaryProjection"]
