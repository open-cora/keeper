"""Keep `proj_execution_procedure_summary` in step with the procedure streams.

The Plan projection's sibling, and the same shape for the same reason: a
procedure has one event. There are no transitions to fold, so there is no
status column and no update statement, and a procedure stream is a single
row that arrives once and never moves.

That makes idempotency easy rather than absent. `ON CONFLICT
(procedure_id) DO NOTHING` is what makes a replayed batch harmless, and
it is load-bearing even here: delivery is at-least-once and the same
genesis will arrive twice sooner or later.

The execution summary is the projection in this context that could not do it
this way, because progress through an execution is not an absolute value. A
step count is: it is read off the genesis payload and every redelivery of
that row carries the same number.

## The name is three things at once

`proj_execution_procedure_summary` is the table, the bookmark row, and
this projection's registered name.
`test_projections_have_a_table_and_a_bookmark.py` is what makes the
agreement a rule rather than a habit.

## The steps are counted and not stored

A procedure may hold a thousand steps and a listing shows fifty
procedures. What the row carries is how long the routine is, which is the
question a list can answer usefully; the steps themselves are one call
away and the log has them either way.
"""

from typing import Any

from keeper.infrastructure.ports.event_store import StoredEvent
from keeper.infrastructure.projection.subscriber import ConnectionLike

PROJECTION_NAME = "proj_execution_procedure_summary"
"""The table, the bookmark row, and the registered name.

One constant because the three must match and they are read in three
different places: the migration that creates the table, the worker that
reads the bookmark, and the adapter that queries the rows.
"""

_GENESIS_EVENT_TYPE = "ProcedureDefined"

_INSERT_SQL = f"""
INSERT INTO {PROJECTION_NAME} (procedure_id, name, beamline, step_count, created_at)
VALUES ($1, $2, $3, $4, $5)
ON CONFLICT (procedure_id) DO NOTHING
"""


class ProcedureSummaryProjection:
    """Folds procedure events into one row per procedure."""

    name = PROJECTION_NAME
    subscribed_event_types = frozenset({_GENESIS_EVENT_TYPE})

    async def apply(self, event: StoredEvent, conn: ConnectionLike) -> None:
        """Write one procedure into the table, inside the worker's transaction.

        No branch, because there is one event type and the subscription
        names it. A second procedure event subscribed to without a branch
        added here would reach this statement and fail looking for a key
        its payload does not carry, which wedges the projection loudly
        rather than writing a wrong row quietly. That is the right way
        round for a read model.
        """
        payload: dict[str, Any] = event.payload
        steps: list[object] = payload["steps"]
        await conn.execute(
            _INSERT_SQL,
            event.stream_id,
            payload["procedure_name"],
            payload["beamline"],
            len(steps),
            event.occurred_at,
        )


__all__ = ["PROJECTION_NAME", "ProcedureSummaryProjection"]
