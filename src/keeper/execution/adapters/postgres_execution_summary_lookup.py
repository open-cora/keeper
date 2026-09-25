"""Read execution summaries out of the projection table.

The deployment half of the `ExecutionSummaryLookup` port. One SELECT against
`proj_execution_execution_summary`, which a background worker keeps in step
with the execution streams.

## Why the ordering is a pair and not a timestamp

Rows come back newest first by `(created_at, execution_id)`, and the id is in
the sort key rather than only in the output. Two executions reported at the
same instant would otherwise have no defined order between them, and a
page boundary landing in the middle of such a tie either repeats a row
or skips one. The id breaks every tie the same way on every page.

That pair is also what the cursor carries, which is why the comparison
below is a row comparison rather than two ANDed inequalities. Postgres
can use the index for the row form.

## Reading one row past the page

The query asks for `limit + 1` rows and the extra one is not returned.
Its presence is the whole answer to "is there a next page", and asking
that way costs one row rather than a second COUNT over the table.

## The count comes out of the array

`reported_indices` holds the steps reported, because a counter cannot be
made idempotent under at-least-once delivery. The port exposes a number,
so the cardinality is taken in SQL rather than by shipping the array to
Python and measuring it here: an execution may hold a thousand indices and
none of them is wanted.
"""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false

from typing import Any
from uuid import UUID

import asyncpg

from keeper.execution.aggregates.execution.state import ExecutionBeamline, ExecutionStatus
from keeper.execution.aggregates.execution.summary import ExecutionSummary, ExecutionSummaryPage
from keeper.execution.projections.execution_summary import PROJECTION_NAME
from keeper.infrastructure.projection.cursor import decode_cursor, encode_cursor

_SELECT_SQL = f"""
SELECT execution_id, procedure_id, procedure_name, beamline,
       step_count, cardinality(reported_indices) AS reported_count,
       status, created_at, updated_at
FROM {PROJECTION_NAME}
WHERE ($1::uuid IS NULL OR procedure_id = $1)
  AND ($2::text IS NULL OR beamline = $2)
  AND ($3::text IS NULL OR status = $3)
  AND ($4::timestamptz IS NULL OR (created_at, execution_id) < ($4, $5))
ORDER BY created_at DESC, execution_id DESC
LIMIT $6
"""


class PostgresExecutionSummaryLookup:
    """Postgres-backed implementation of the `ExecutionSummaryLookup` port."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def list_executions(
        self,
        *,
        procedure_id: UUID | None,
        beamline: ExecutionBeamline | None,
        status: ExecutionStatus | None,
        limit: int,
        cursor: str | None,
    ) -> ExecutionSummaryPage:
        """Return one page of executions, newest first."""
        after = decode_cursor(cursor) if cursor is not None else None
        rows = await self._pool.fetch(
            _SELECT_SQL,
            procedure_id,
            beamline.value if beamline is not None else None,
            status.value if status is not None else None,
            after[0] if after is not None else None,
            after[1] if after is not None else None,
            limit + 1,
        )

        has_more = len(rows) > limit
        items = [_to_summary(row) for row in rows[:limit]]
        next_cursor = (
            encode_cursor(created_at=items[-1].created_at, item_id=items[-1].execution_id)
            if has_more and items
            else None
        )
        return ExecutionSummaryPage(items=items, next_cursor=next_cursor)


def _to_summary(row: Any) -> ExecutionSummary:
    return ExecutionSummary(
        execution_id=row["execution_id"],
        procedure_id=row["procedure_id"],
        procedure_name=row["procedure_name"],
        beamline=ExecutionBeamline(row["beamline"]),
        step_count=row["step_count"],
        reported_count=row["reported_count"],
        status=ExecutionStatus(row["status"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


__all__ = ["PostgresExecutionSummaryLookup"]
