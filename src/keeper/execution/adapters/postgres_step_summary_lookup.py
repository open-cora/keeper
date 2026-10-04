"""Read step summaries out of the projection table.

The deployment half of the `StepSummaryLookup` port. One SELECT against
`proj_execution_step_summary`, which a background worker keeps in step
with the execution streams and with Custody's dataset streams.

## The filter is in the WHERE and not in the caller

The question is "which steps should have produced data and did not",
and it is fixed here rather than passed in.

`opens_a_run` is what makes it that question. The gate used to be
`run_opened_at`, which only a watcher writes, so the listing found a
run somebody saw open and recorded nothing, and could not find a run
nobody saw at all. The second loses every run at a beamline rather than
one, and was measured doing exactly that: a scan at a commissioned
beamline with its reporter stopped walked to Done, wrote a file and
registered nothing, and never appeared here. Whether driving a step
opens a run is a property of the procedure it came from, known before
any client is involved, so that is what is asked.

`reported_at` is still required. A run enters this table when it
begins, so without it every scan currently running reads as a run whose
data nobody recorded.

The outcome clause is new, and it is paying for the gate. A step that
was skipped or refused never ran, and used to be excluded for free
because nothing had opened on it. Gating on the definition admits them,
so they come out by name. `Broken` stays in: a run that broke may have
written data before it did, and a reader has the outcome in front of
them.

## Why `run_opened_at` is returned now that it decides nothing

Because the two kinds of gap want different people. A run watched and
unfiled is a filing or engine fault; a run with no `run_opened_at` is a
beamline nobody is reporting. Returning the column lets a caller tell
them apart, where gating on it showed only the first and hid the second.

The table holds every step of every execution and the overwhelming
majority of those rows are moves, which produced nothing and are
missing nothing. A port that let a caller drop the filter would offer a
listing of an entire facility's steps as a page of fifty, and nothing
asks for that.

The partial index in the migration matches these three predicates, so
the scan is over the gaps rather than over the table.

## Why the ordering is a pair and not a timestamp

Rows come back newest first by `(reported_at, step_id)`, and the id is
in the sort key rather than only in the output. Two steps reported in
the same instant would otherwise have no defined order between them,
and a page boundary landing in such a tie either repeats a row or skips
one.

`reported_at` is nullable on the table and never null in this result,
because the filter requires it. The sort key is therefore total over
the rows this returns, which is what a keyset cursor needs.
"""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false

from typing import Any

import asyncpg

from keeper.execution.aggregates.execution.state import ExecutionBeamline
from keeper.execution.aggregates.execution.step_summary import StepSummary, StepSummaryPage
from keeper.execution.projections.step_summary import PROJECTION_NAME
from keeper.infrastructure.projection.cursor import decode_cursor, encode_cursor

_SELECT_SQL = f"""
SELECT step_id, execution_id, step_index, describes, beamline,
       outcome, engine_reference, reported_at, run_opened_at, dataset_id, filed_at
FROM {PROJECTION_NAME}
WHERE opens_a_run
  AND reported_at IS NOT NULL
  AND outcome IN ('Done', 'Broken')
  AND dataset_id IS NULL
  AND ($1::text IS NULL OR beamline = $1)
  AND ($2::timestamptz IS NULL OR (reported_at, step_id) < ($2, $3))
ORDER BY reported_at DESC, step_id DESC
LIMIT $4
"""


class PostgresStepSummaryLookup:
    """Postgres-backed implementation of the `StepSummaryLookup` port."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def list_steps_without_datasets(
        self,
        *,
        beamline: ExecutionBeamline | None,
        limit: int,
        cursor: str | None,
    ) -> StepSummaryPage:
        """Return one page of runs whose output nothing recorded."""
        after = decode_cursor(cursor) if cursor is not None else None
        rows = await self._pool.fetch(
            _SELECT_SQL,
            beamline.value if beamline is not None else None,
            after[0] if after is not None else None,
            after[1] if after is not None else None,
            limit + 1,
        )

        has_more = len(rows) > limit
        items = [_to_summary(row) for row in rows[:limit]]
        next_cursor = _cursor_after(items) if has_more and items else None
        return StepSummaryPage(items=items, next_cursor=next_cursor)


def _cursor_after(items: list[StepSummary]) -> str | None:
    """The sort key of the last row, or nothing when it has no time.

    The guard is unreachable against this query, which requires a
    reported time in its filter. It is
    here because the column is nullable and a cursor built from a null
    would decode into a page boundary nothing compares against, which
    reads to a caller as a listing that silently ends early.
    """
    last = items[-1]
    if last.reported_at is None:
        return None
    return encode_cursor(created_at=last.reported_at, item_id=last.step_id)


def _to_summary(row: Any) -> StepSummary:
    return StepSummary(
        step_id=row["step_id"],
        execution_id=row["execution_id"],
        index=row["step_index"],
        describes=row["describes"],
        beamline=ExecutionBeamline(row["beamline"]),
        outcome=row["outcome"],
        engine_reference=row["engine_reference"],
        reported_at=row["reported_at"],
        run_opened_at=row["run_opened_at"],
        dataset_id=row["dataset_id"],
        filed_at=row["filed_at"],
    )


__all__ = ["PostgresStepSummaryLookup"]
