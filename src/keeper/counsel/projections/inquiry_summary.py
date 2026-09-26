"""Keep `proj_counsel_inquiry_summary` in step with the inquiry streams.

Three arms, one per event, which makes it the second-largest projection in
this tree: more than the proposal's two, well short of the execution's many.

## The name is three things at once

`proj_counsel_inquiry_summary` is the table, the bookmark row, and this
projection's registered name. They have to agree, because the worker finds
the bookmark by the name and the SQL below finds the table by spelling it,
and `test_projections_have_a_table_and_a_bookmark.py` is what makes the
agreement a rule rather than a habit.

## Running twice must be harmless

Delivery is at-least-once. The worker advances its bookmark in the same
transaction as the writes, so a crash between the two replays the batch, and
a replayed batch has to leave the table where the first pass left it.

The genesis takes `ON CONFLICT (inquiry_id) DO NOTHING`. Both transitions
are idempotent for a different reason and it is worth being explicit: each
writes the same values every time, derived entirely from the event rather
than from what the row currently holds, so applying one twice is applying it
once.

## Why the updates are not conditional

Neither transition checks the row's current state. The decider already
refuses a second claim and a second answer, so a stream carrying either is a
stream that could not have been written, and an arm defending against one
would be defending against a state the write side makes impossible.

The answer arm does not test `claimed_at` either, and that is not an
oversight: answering an unclaimed inquiry is allowed, so a row can go from
both-null to answered in one step.

## Why there is no status column

The table stores two nullable timestamps and derives the three states from
them, which is the call the proposal table makes for its two. A status
column beside them would be one fact written twice, and two spellings are
two things these arms could write inconsistently.
"""

from typing import Any
from uuid import UUID

from keeper.infrastructure.logging import get_logger
from keeper.infrastructure.ports.event_store import StoredEvent
from keeper.infrastructure.projection.subscriber import ConnectionLike

PROJECTION_NAME = "proj_counsel_inquiry_summary"
"""The table, the bookmark row, and the registered name.

One constant because the three must match and they are read in three
different places: the migration that creates the table, the worker that
reads the bookmark, and the adapter that queries the rows.
"""

_GENESIS_EVENT_TYPE = "InquiryMade"
_CLAIMED_EVENT_TYPE = "InquiryClaimed"
_ANSWERED_EVENT_TYPE = "InquiryAnswered"

_INSERT_SQL = f"""
INSERT INTO {PROJECTION_NAME} (
    inquiry_id, actor_id, execution_id, objective, execution_step_count,
    conclusion, observed_step_count, execution_ended, proposal_id,
    created_at, claimed_at, answered_at
) VALUES ($1, $2, $3, $4, $5, NULL, NULL, NULL, NULL, $6, NULL, NULL)
ON CONFLICT (inquiry_id) DO NOTHING
"""

_CLAIM_SQL = f"""
UPDATE {PROJECTION_NAME}
SET claimed_at = $2
WHERE inquiry_id = $1
"""

_ANSWER_SQL = f"""
UPDATE {PROJECTION_NAME}
SET conclusion = $2,
    observed_step_count = $3,
    execution_ended = $4,
    proposal_id = $5,
    answered_at = $6
WHERE inquiry_id = $1
"""

_log = get_logger(__name__)


class InquirySummaryProjection:
    """Folds inquiry events into one row per inquiry."""

    name = PROJECTION_NAME
    subscribed_event_types = frozenset(
        {_GENESIS_EVENT_TYPE, _CLAIMED_EVENT_TYPE, _ANSWERED_EVENT_TYPE}
    )

    async def apply(self, event: StoredEvent, conn: ConnectionLike) -> None:
        """Write one event into the table, inside the worker's transaction.

        Raising rolls the whole batch back and leaves the bookmark where it
        was, so an event this cannot handle is retried forever rather than
        skipped. That is the right failure for a read model: stale and loud
        beats wrong and quiet.
        """
        if event.event_type == _GENESIS_EVENT_TYPE:
            await self._insert(event, conn)
            return
        if event.event_type == _CLAIMED_EVENT_TYPE:
            await self._claim(event, conn)
            return
        await self._answer(event, conn)

    async def _insert(self, event: StoredEvent, conn: ConnectionLike) -> None:
        """Write the genesis row, open and unanswered.

        `inquiry_id` comes off the envelope rather than the payload: the
        stream id is what all three statements here agree on, and reading it
        from the payload would let one statement point at a different
        inquiry than another.

        `created_at` is the envelope's domain time, which for this event is
        this system's own clock reading, because asking is an act performed
        here rather than one reported to it.
        """
        payload: dict[str, Any] = event.payload
        await conn.execute(
            _INSERT_SQL,
            event.stream_id,
            UUID(payload["actor_id"]),
            UUID(payload["execution_id"]),
            payload["objective"],
            payload["execution_step_count"],
            event.occurred_at,
        )

    async def _claim(self, event: StoredEvent, conn: ConnectionLike) -> None:
        """Stamp the row as taken up, or say so when there is none."""
        result = await conn.execute(_CLAIM_SQL, event.stream_id, event.occurred_at)
        self._warn_if_no_row(result, event, arm="claim")

    async def _answer(self, event: StoredEvent, conn: ConnectionLike) -> None:
        """Write the conclusion and the observation boundary onto the row.

        All five values come off one event, so the row cannot end up holding
        a conclusion without the boundary it was reached from.

        `answered_at` is the envelope's domain time, which for this event may
        be a caller's claim rather than a clock reading, because the thinking
        happened somewhere else.
        """
        payload: dict[str, Any] = event.payload
        raw_proposal_id = payload["proposal_id"]
        result = await conn.execute(
            _ANSWER_SQL,
            event.stream_id,
            payload["conclusion"],
            payload["observed_step_count"],
            payload["execution_ended"],
            None if raw_proposal_id is None else UUID(raw_proposal_id),
            event.occurred_at,
        )
        self._warn_if_no_row(result, event, arm="answer")

    def _warn_if_no_row(self, result: object, event: StoredEvent, *, arm: str) -> None:
        """Log a transition that found no row to land on.

        That means the genesis is missing, which the ordering guarantees
        cannot happen: events arrive in `(transaction_id, position)` order
        and an inquiry's own events share a stream. It is logged rather than
        raised, because the alternative is wedging the whole projection over
        one inquiry, and a warning naming it is what an operator needs to
        rebuild.
        """
        if isinstance(result, str) and result.endswith(" 0"):
            _log.warning(
                "inquiry_summary.transition_without_row",
                projection=PROJECTION_NAME,
                arm=arm,
                inquiry_id=str(event.stream_id),
                position=event.position,
            )


__all__ = ["PROJECTION_NAME", "InquirySummaryProjection"]
