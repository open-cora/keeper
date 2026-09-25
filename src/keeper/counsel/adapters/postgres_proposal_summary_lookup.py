"""Read proposal summaries out of the projection table.

The deployment half of the `ProposalSummaryLookup` port. One SELECT
against `proj_counsel_proposal_summary`, which a background worker keeps
in step with the proposal streams.

## Why the ordering is a pair and not a timestamp

Rows come back newest first by `(created_at, proposal_id)`, and the id is
in the sort key rather than only in the output. Two proposals made at the
same instant would otherwise have no defined order between them, and a
page boundary landing in the middle of such a tie either repeats a row or
skips one.

The tie is not hypothetical here, and it is likelier than next door. A
dataset's timestamp is a caller's claim, so ties come from backfills; a
proposal's comes from this system's own clock, so an agent that makes
several proposals in one turn can produce them inside a single clock
tick.

That pair is also what the cursor carries, which is why the comparison
below is a row comparison rather than two ANDed inequalities. Postgres
can use the index for the row form.

## Reading one row past the page

The query asks for `limit + 1` rows and the extra one is not returned.
Its presence is the whole answer to "is there a next page", and asking
that way costs one row rather than a second COUNT query over the table.
The cursor handed back is the sort key of the LAST row actually
returned, so the next page resumes exactly where this one stopped.

## Why openness is a null test and not a column

`execution_id IS NULL` is the filter, because the null is the status. A
boolean column beside it would be a second spelling of one bit, and a
projection that wrote the two inconsistently is a class of bug the
absence makes impossible.

The root is tested rather than the step, and either would do: the two
columns are written by one statement from one event, so a row with one
of them set is not a row this projection can produce.
"""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false

from typing import Any

import asyncpg

from keeper.counsel.aggregates.proposal.summary import ProposalSummary, ProposalSummaryPage
from keeper.counsel.projections.proposal_summary import PROJECTION_NAME
from keeper.infrastructure.projection.cursor import decode_cursor, encode_cursor

_SELECT_SQL = f"""
SELECT proposal_id, actor_id, plan_id, execution_id, step_id, created_at, taken_at
FROM {PROJECTION_NAME}
WHERE ($1::boolean IS NULL
       OR ($1 IS TRUE AND execution_id IS NULL)
       OR ($1 IS FALSE AND execution_id IS NOT NULL))
  AND ($2::timestamptz IS NULL OR (created_at, proposal_id) < ($2, $3))
ORDER BY created_at DESC, proposal_id DESC
LIMIT $4
"""


class PostgresProposalSummaryLookup:
    """Postgres-backed implementation of the `ProposalSummaryLookup` port."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def list_proposals(
        self,
        *,
        is_open: bool | None,
        limit: int,
        cursor: str | None,
    ) -> ProposalSummaryPage:
        """Return one page of proposals, newest first."""
        after = decode_cursor(cursor) if cursor is not None else None
        rows = await self._pool.fetch(
            _SELECT_SQL,
            is_open,
            after[0] if after is not None else None,
            after[1] if after is not None else None,
            limit + 1,
        )

        has_more = len(rows) > limit
        items = [_to_summary(row) for row in rows[:limit]]
        next_cursor = (
            encode_cursor(created_at=items[-1].created_at, item_id=items[-1].proposal_id)
            if has_more and items
            else None
        )
        return ProposalSummaryPage(items=items, next_cursor=next_cursor)


def _to_summary(row: Any) -> ProposalSummary:
    return ProposalSummary(
        proposal_id=row["proposal_id"],
        actor_id=row["actor_id"],
        plan_id=row["plan_id"],
        execution_id=row["execution_id"],
        step_id=row["step_id"],
        created_at=row["created_at"],
        taken_at=row["taken_at"],
    )


__all__ = ["PostgresProposalSummaryLookup"]
