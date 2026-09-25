"""Read dataset summaries out of the projection table.

The deployment half of the `DatasetSummaryLookup` port. One SELECT against
`proj_custody_dataset_summary`, which a background worker keeps in step
with the dataset streams.

## Why the ordering is a pair and not a timestamp

Rows come back newest first by `(created_at, dataset_id)`, and the id is
in the sort key rather than only in the output. Two datasets written at
the same instant, which a backfill produces routinely and which a run
producing several at once produces by design, would otherwise have no
defined order between them, and a page boundary landing in the middle of
such a tie either repeats a row or skips one. The id breaks every tie the
same way on every page.

That pair is also what the cursor carries, which is why the comparison
below is a row comparison, `(created_at, dataset_id) < (...)`, rather
than two ANDed inequalities. Postgres can use the index for the row form.

## Reading one row past the page

The query asks for `limit + 1` rows and the extra one is not returned. Its
presence is the whole answer to "is there a next page", and asking that
way costs one row rather than a second COUNT query over the table. The
cursor handed back is the sort key of the LAST row actually returned, so
the next page resumes exactly where this one stopped.
"""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false

from typing import Any
from uuid import UUID

import asyncpg

from keeper.custody.aggregates.dataset.summary import DatasetSummary, DatasetSummaryPage
from keeper.custody.projections.dataset_summary import PROJECTION_NAME
from keeper.infrastructure.projection.cursor import decode_cursor, encode_cursor
from keeper.shared.identifier import Identifier

_SELECT_SQL = f"""
SELECT dataset_id, execution_id, step_id, external_ref_scheme, external_ref_value, created_at
FROM {PROJECTION_NAME}
WHERE ($1::uuid IS NULL OR step_id = $1)
  AND ($2::timestamptz IS NULL OR (created_at, dataset_id) < ($2, $3))
ORDER BY created_at DESC, dataset_id DESC
LIMIT $4
"""


class PostgresDatasetSummaryLookup:
    """Postgres-backed implementation of the `DatasetSummaryLookup` port."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def list_datasets(
        self,
        *,
        step_id: UUID | None,
        limit: int,
        cursor: str | None,
    ) -> DatasetSummaryPage:
        """Return one page of datasets, newest first."""
        after = decode_cursor(cursor) if cursor is not None else None
        rows = await self._pool.fetch(
            _SELECT_SQL,
            step_id,
            after[0] if after is not None else None,
            after[1] if after is not None else None,
            limit + 1,
        )

        has_more = len(rows) > limit
        items = [_to_summary(row) for row in rows[:limit]]
        next_cursor = (
            encode_cursor(created_at=items[-1].created_at, item_id=items[-1].dataset_id)
            if has_more and items
            else None
        )
        return DatasetSummaryPage(items=items, next_cursor=next_cursor)


def _to_summary(row: Any) -> DatasetSummary:
    return DatasetSummary(
        dataset_id=row["dataset_id"],
        execution_id=row["execution_id"],
        step_id=row["step_id"],
        external_ref=Identifier(
            scheme=row["external_ref_scheme"],
            value=row["external_ref_value"],
        ),
        created_at=row["created_at"],
    )


__all__ = ["PostgresDatasetSummaryLookup"]
