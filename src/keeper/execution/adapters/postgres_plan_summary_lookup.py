"""Read plan summaries out of the projection table.

The deployment half of the `PlanSummaryLookup` port, and the execution
lookup's sibling. Same keyset ordering on `(created_at, plan_id)`, same
reason for the id being in the sort key rather than only in the output,
same read-one-row-past-the-page trick for deciding whether a next page
exists. Read `postgres_execution_summary_lookup.py` for the reasoning
behind all three; it is written out there and not repeated here.

One difference. Filtering by name is an equality on a column that is not
unique and is not meant to be, so this is the query most likely to return
two rows where a caller expected one. Nothing here smooths that over.
"""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false

from typing import Any

import asyncpg

from keeper.execution.aggregates.plan.state import PlanName
from keeper.execution.aggregates.plan.summary import PlanSummary, PlanSummaryPage
from keeper.execution.projections.plan_summary import PROJECTION_NAME
from keeper.infrastructure.projection.cursor import decode_cursor, encode_cursor

_SELECT_SQL = f"""
SELECT plan_id, name, created_at
FROM {PROJECTION_NAME}
WHERE ($1::text IS NULL OR name = $1)
  AND ($2::timestamptz IS NULL OR (created_at, plan_id) < ($2, $3))
ORDER BY created_at DESC, plan_id DESC
LIMIT $4
"""


class PostgresPlanSummaryLookup:
    """Postgres-backed implementation of the `PlanSummaryLookup` port."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def list_plans(
        self,
        *,
        name: PlanName | None,
        limit: int,
        cursor: str | None,
    ) -> PlanSummaryPage:
        """Return one page of plans, newest first."""
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
            encode_cursor(created_at=items[-1].created_at, item_id=items[-1].plan_id)
            if has_more and items
            else None
        )
        return PlanSummaryPage(items=items, next_cursor=next_cursor)


def _to_summary(row: Any) -> PlanSummary:
    return PlanSummary(
        plan_id=row["plan_id"],
        name=PlanName(row["name"]),
        created_at=row["created_at"],
    )


__all__ = ["PostgresPlanSummaryLookup"]
