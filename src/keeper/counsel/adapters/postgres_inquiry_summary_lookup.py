"""Read inquiry summaries out of the projection table.

The deployment half of the `InquirySummaryLookup` port. One SELECT against
`proj_counsel_inquiry_summary`, which a background worker keeps in step with
the inquiry streams.

## Why the ordering is a pair and not a timestamp

Rows come back newest first by `(created_at, inquiry_id)`, and the id is in
the sort key rather than only in the output. Two inquiries made at the same
instant would otherwise have no defined order between them, and a page
boundary landing in the middle of such a tie either repeats a row or skips
one. The timestamp is this system's own clock rather than a caller's claim,
so an agent asking several questions in one turn can land them inside a
single tick.

That pair is also what the cursor carries, which is why the comparison below
is a row comparison rather than two ANDed inequalities. Postgres can use the
index for the row form.

## Reading one row past the page

The query asks for `limit + 1` rows and the extra one is not returned. Its
presence is the whole answer to "is there a next page", and asking that way
costs one row rather than a second COUNT query over the table.

## Why the status is three null tests and not a column

The table stores no status. Two nullable timestamps carry the three states,
because a column beside them would be one fact written twice and the
projection could write the two inconsistently. So the filter spells the
derivation out, and `_status_of` spells the same derivation for the rows
coming back. They are the only two places it exists, and the port contract
suite is what keeps them agreeing with the fold that the other adapter uses.

The answered test does not mention `claimed_at`, deliberately. Answering an
unclaimed inquiry is allowed, so an answered row may have either.
"""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false

from datetime import datetime
from typing import Any

import asyncpg

from keeper.counsel.aggregates.inquiry.state import InquiryConclusion, InquiryStatus
from keeper.counsel.aggregates.inquiry.summary import InquirySummary, InquirySummaryPage
from keeper.counsel.projections.inquiry_summary import PROJECTION_NAME
from keeper.infrastructure.projection.cursor import decode_cursor, encode_cursor

_SELECT_SQL = f"""
SELECT inquiry_id, actor_id, execution_id, objective, execution_step_count,
       conclusion, observed_step_count, execution_ended, proposal_id,
       created_at, claimed_at, answered_at
FROM {PROJECTION_NAME}
WHERE ($1::text IS NULL
       OR ($1 = 'Open' AND claimed_at IS NULL AND answered_at IS NULL)
       OR ($1 = 'Claimed' AND claimed_at IS NOT NULL AND answered_at IS NULL)
       OR ($1 = 'Answered' AND answered_at IS NOT NULL))
  AND ($2::timestamptz IS NULL OR (created_at, inquiry_id) < ($2, $3))
ORDER BY created_at DESC, inquiry_id DESC
LIMIT $4
"""


class PostgresInquirySummaryLookup:
    """Postgres-backed implementation of the `InquirySummaryLookup` port."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def list_inquiries(
        self,
        *,
        status: InquiryStatus | None,
        limit: int,
        cursor: str | None,
    ) -> InquirySummaryPage:
        """Return one page of inquiries, newest first."""
        after = decode_cursor(cursor) if cursor is not None else None
        rows = await self._pool.fetch(
            _SELECT_SQL,
            None if status is None else status.value,
            after[0] if after is not None else None,
            after[1] if after is not None else None,
            limit + 1,
        )

        has_more = len(rows) > limit
        items = [_to_summary(row) for row in rows[:limit]]
        next_cursor = (
            encode_cursor(created_at=items[-1].created_at, item_id=items[-1].inquiry_id)
            if has_more and items
            else None
        )
        return InquirySummaryPage(items=items, next_cursor=next_cursor)


def _status_of(claimed_at: datetime | None, answered_at: datetime | None) -> InquiryStatus:
    """Derive the status the fold would have produced, from the two stamps.

    Answered wins over claimed, because an answer is the terminal and the
    order the two arrived in does not change where the inquiry ended up.
    """
    if answered_at is not None:
        return InquiryStatus.ANSWERED
    if claimed_at is not None:
        return InquiryStatus.CLAIMED
    return InquiryStatus.OPEN


def _to_summary(row: Any) -> InquirySummary:
    raw_conclusion = row["conclusion"]
    return InquirySummary(
        inquiry_id=row["inquiry_id"],
        actor_id=row["actor_id"],
        execution_id=row["execution_id"],
        objective=row["objective"],
        execution_step_count=row["execution_step_count"],
        status=_status_of(row["claimed_at"], row["answered_at"]),
        conclusion=None if raw_conclusion is None else InquiryConclusion(raw_conclusion),
        observed_step_count=row["observed_step_count"],
        execution_ended=row["execution_ended"],
        proposal_id=row["proposal_id"],
        created_at=row["created_at"],
        claimed_at=row["claimed_at"],
        answered_at=row["answered_at"],
    )


__all__ = ["PostgresInquirySummaryLookup"]
