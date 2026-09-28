"""Fold pursuit events into one row per pursuit.

Five of the six event types land here and one does not. A charge moves no
column on this row, because what a pursuit has spent is not on it: five
numbers against five limits, one of which depends on the clock at the
moment of asking. Subscribing to an event this does nothing with would
make the worker wake for every token a thinker reports.

## Every arm writes values the event carries

Delivery is at-least-once, so an arm that read the row before writing it
would count a redelivered event twice. None of them does.

The round-count arm is the one where that took a decision rather than
falling out. A counter is the natural shape and it is the wrong one: the
count is written as the round's own index plus one, so a round delivered
twice writes the same number twice.

The status arm is the other. It writes the status the outcome implies
rather than reading what is there and moving it, so a close delivered
twice leaves the row where the first one left it.

## Why this one stores a status where the inquiry table refused to

An inquiry's three states only ever go forwards, so two nullable
timestamps carry the whole of it and a status column would be one fact
written twice. A pursuit's go backwards: held becomes running when
somebody resumes, and may become held again next round. Timestamps would
have to record the last of an unbounded sequence rather than whether
something happened.

That is the split across the read models here, and it is not stored
against derived: the execution and device summaries both carry a status
column too, and a device recovers much the way a pursuit resumes. What
decides it is whether the states go one way.

A written status can disagree with the fold, which is the cost all three
pay. Both sides here answer one port contract suite and neither can see
the other, which is the only thing that makes the claim checkable.
"""

from typing import Any
from uuid import UUID

from keeper.infrastructure.logging import get_logger
from keeper.infrastructure.ports.event_store import StoredEvent
from keeper.infrastructure.projection.subscriber import ConnectionLike
from keeper.pursuit.aggregates.pursuit import PursuitStatus, RoundOutcome

PROJECTION_NAME = "proj_pursuit_pursuit_summary"
"""The table, the bookmark row, and the registered name.

One constant because the three must match and they are read in three
different places: the migration that creates the table, the worker that
reads the bookmark, and the adapter that queries the rows.
"""

_GENESIS_EVENT_TYPE = "PursuitStarted"
_OPENED_EVENT_TYPE = "PursuitRoundOpened"
_CLOSED_EVENT_TYPE = "PursuitRoundClosed"
_RESUMED_EVENT_TYPE = "PursuitResumed"
_WITHDRAWN_EVENT_TYPE = "PursuitWithdrawn"

_INSERT_SQL = f"""
INSERT INTO {PROJECTION_NAME} (
    pursuit_id, actor_id, goal, beamline, status, held_for, round_count,
    created_at, stopped_at
) VALUES ($1, $2, $3, $4, $5, NULL, 0, $6, NULL)
ON CONFLICT (pursuit_id) DO NOTHING
"""

_COUNT_SQL = f"""
UPDATE {PROJECTION_NAME}
SET round_count = GREATEST(round_count, $2)
WHERE pursuit_id = $1
"""

_CLOSE_SQL = f"""
UPDATE {PROJECTION_NAME}
SET status = $2,
    held_for = $3
WHERE pursuit_id = $1
"""

_RESUME_SQL = f"""
UPDATE {PROJECTION_NAME}
SET status = $2,
    held_for = NULL
WHERE pursuit_id = $1
"""

_WITHDRAW_SQL = f"""
UPDATE {PROJECTION_NAME}
SET status = $2,
    held_for = NULL,
    stopped_at = $3
WHERE pursuit_id = $1
"""

_AFTER: dict[RoundOutcome, PursuitStatus] = {
    RoundOutcome.ADVANCED: PursuitStatus.RUNNING,
    RoundOutcome.COMPLETED: PursuitStatus.STOPPED,
    RoundOutcome.STALLED: PursuitStatus.HELD,
    RoundOutcome.REFERRED: PursuitStatus.HELD,
}
"""Which status each outcome leaves the pursuit in.

The same mapping the evolver makes, written out here rather than imported
from it. That is the duplication this projection is: a read model that
reached into the write side's fold would agree with it by construction and
prove nothing, and the port contract suite is what checks the two spellings
say the same thing.

A mapping rather than branches, so a fifth outcome fails the lookup and
wedges this projection loudly, instead of falling through to a default and
quietly leaving a row in the wrong state.
"""

_log = get_logger(__name__)


class PursuitSummaryProjection:
    """Folds pursuit events into one row per pursuit."""

    name = PROJECTION_NAME
    subscribed_event_types = frozenset(
        {
            _GENESIS_EVENT_TYPE,
            _OPENED_EVENT_TYPE,
            _CLOSED_EVENT_TYPE,
            _RESUMED_EVENT_TYPE,
            _WITHDRAWN_EVENT_TYPE,
        }
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
        elif event.event_type == _OPENED_EVENT_TYPE:
            await self._count(event, conn)
        elif event.event_type == _CLOSED_EVENT_TYPE:
            await self._close(event, conn)
        elif event.event_type == _RESUMED_EVENT_TYPE:
            await self._resume(event, conn)
        else:
            await self._withdraw(event, conn)

    async def _insert(self, event: StoredEvent, conn: ConnectionLike) -> None:
        """Write the genesis row, running and with no rounds.

        `pursuit_id` comes off the envelope rather than the payload: the
        stream id is what every statement here agrees on, and reading it
        from the payload would let one statement point at a different
        pursuit than another.

        `created_at` is the envelope's domain time, which for this event is
        this system's own clock reading, because authorizing is an act
        performed here rather than one reported to it.
        """
        payload: dict[str, Any] = event.payload
        await conn.execute(
            _INSERT_SQL,
            event.stream_id,
            UUID(payload["actor_id"]),
            payload["goal"],
            payload["beamline"],
            PursuitStatus.RUNNING.value,
            event.occurred_at,
        )

    async def _count(self, event: StoredEvent, conn: ConnectionLike) -> None:
        """Raise the count to what this round's own number implies.

        `GREATEST` rather than assignment, and the index rather than an
        increment. The index makes a redelivered round write the number it
        wrote before; the `GREATEST` makes an out-of-order redelivery of an
        earlier round leave a later one alone. Ordering says the second
        cannot happen, and the cost of surviving it anyway is one function
        call.
        """
        payload: dict[str, Any] = event.payload
        result = await conn.execute(_COUNT_SQL, event.stream_id, int(payload["round_index"]) + 1)
        self._warn_if_no_row(result, event, arm="count")

    async def _close(self, event: StoredEvent, conn: ConnectionLike) -> None:
        """Move the status to whatever the outcome implies.

        The outcome is narrowed to the enum before the lookup, so a value
        that is no longer one of the four raises here rather than writing a
        status nothing recognises.
        """
        payload: dict[str, Any] = event.payload
        outcome = RoundOutcome(payload["outcome"])
        status = _AFTER[outcome]
        result = await conn.execute(
            _CLOSE_SQL,
            event.stream_id,
            status.value,
            outcome.value if status is PursuitStatus.HELD else None,
        )
        self._warn_if_no_row(result, event, arm="close")

    async def _resume(self, event: StoredEvent, conn: ConnectionLike) -> None:
        """Put the row back to running and forget why it was held."""
        result = await conn.execute(_RESUME_SQL, event.stream_id, PursuitStatus.RUNNING.value)
        self._warn_if_no_row(result, event, arm="resume")

    async def _withdraw(self, event: StoredEvent, conn: ConnectionLike) -> None:
        """Stop the row, and record when.

        `held_for` is cleared as well as the status being set, because a
        pursuit withdrawn while held is stopped rather than still waiting,
        and a reason left behind would say a person is expected who is not.
        """
        result = await conn.execute(
            _WITHDRAW_SQL,
            event.stream_id,
            PursuitStatus.STOPPED.value,
            event.occurred_at,
        )
        self._warn_if_no_row(result, event, arm="withdraw")

    def _warn_if_no_row(self, result: object, event: StoredEvent, *, arm: str) -> None:
        """Log a transition that found no row to land on.

        That means the genesis is missing, which the ordering guarantees
        cannot happen: events arrive in `(transaction_id, position)` order
        and a pursuit's own events share a stream. It is logged rather than
        raised, because the alternative is wedging the whole projection over
        one pursuit, and a warning naming it is what an operator needs to
        rebuild.
        """
        if isinstance(result, str) and result.endswith(" 0"):
            _log.warning(
                "pursuit_summary.transition_without_row",
                projection=PROJECTION_NAME,
                arm=arm,
                pursuit_id=str(event.stream_id),
                position=event.position,
            )


__all__ = ["PROJECTION_NAME", "PursuitSummaryProjection"]
