"""Read procedure summaries out of the projection table.

The deployment half of the `ProcedureSummaryLookup` port, and the plan
lookup's sibling. Same keyset ordering on `(created_at, procedure_id)`,
same reason for the id being in the sort key rather than only in the
output, same read-one-row-past-the-page trick for deciding whether a next
page exists. Read `postgres_execution_summary_lookup.py` for the reasoning
behind all three; it is written out there and not repeated here.

Filtering by name is an equality on a column that is not unique and is
not meant to be, so this query can return two rows where a caller
expected one. Nothing here smooths that over.
"""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false

from typing import Any

import asyncpg

from keeper.execution.aggregates.procedure.state import ProcedureBeamline, ProcedureName
from keeper.execution.aggregates.procedure.summary import (
    ProcedureSummary,
    ProcedureSummaryPage,
)
from keeper.execution.projections.procedure_summary import PROJECTION_NAME
from keeper.infrastructure.projection.cursor import decode_cursor, encode_cursor

_SELECT_SQL = f"""
SELECT procedure_id, name, beamline, step_count, created_at
FROM {PROJECTION_NAME}
WHERE ($1::text IS NULL OR name = $1)
  AND ($2::timestamptz IS NULL OR (created_at, procedure_id) < ($2, $3))
ORDER BY created_at DESC, procedure_id DESC
LIMIT $4
"""


class PostgresProcedureSummaryLookup:
    """Postgres-backed implementation of the `ProcedureSummaryLookup` port."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def list_procedures(
        self,
        *,
        name: ProcedureName | None,
        limit: int,
        cursor: str | None,
    ) -> ProcedureSummaryPage:
        """Return one page of procedures, newest first."""
        after = decode_cursor(cursor) if cursor is not None else None
        rows = await self._pool.fetch(
            _SELECT_SQL,
            name.value if name is not None else None,
            after[0] if after is not None else None,
            after[1] if after is not None else None,
            limit + 1,
        )

        has_more = len(rows) > limit
        items = [_to_summary(row) for row in rows[:limit]]
        next_cursor = (
            encode_cursor(created_at=items[-1].created_at, item_id=items[-1].procedure_id)
            if has_more and items
            else None
        )
        return ProcedureSummaryPage(items=items, next_cursor=next_cursor)


def _to_summary(row: Any) -> ProcedureSummary:
    return ProcedureSummary(
        procedure_id=row["procedure_id"],
        name=ProcedureName(row["name"]),
        beamline=ProcedureBeamline(row["beamline"]),
        step_count=row["step_count"],
        created_at=row["created_at"],
    )


__all__ = ["PostgresProcedureSummaryLookup"]
