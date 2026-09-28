"""Read a page of pursuits out of the table a worker maintains.

The Postgres half of the `PursuitSummaryLookup` port. One statement, two
optional filters and a keyset cursor, which is the shape every list in
this tree has.

## Why the status is read rather than derived

The sibling adapters rebuild a status out of nullable timestamps, because
their aggregates only ever move one way. This one reads a column, because
a pursuit's status goes backwards and a pair of stamps cannot say which
way it went last.

That is the one thing this adapter takes on trust from the projection,
and it is the reason both halves of this port answer the same contract
suite. The fold and the table agree because a test says so, not because
either can see the other.
"""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false

from typing import Any

import asyncpg

from keeper.infrastructure.projection.cursor import decode_cursor, encode_cursor
from keeper.pursuit.aggregates.pursuit.state import PursuitStatus, RoundOutcome
from keeper.pursuit.aggregates.pursuit.summary import PursuitSummary, PursuitSummaryPage
from keeper.pursuit.projections.pursuit_summary import PROJECTION_NAME

_SELECT_SQL = f"""
SELECT pursuit_id, actor_id, goal, beamline, status, held_for, round_count,
       created_at, stopped_at
FROM {PROJECTION_NAME}
WHERE ($1::text IS NULL OR status = $1)
  AND ($2::text IS NULL OR beamline = $2)
  AND ($3::timestamptz IS NULL OR (created_at, pursuit_id) < ($3, $4))
ORDER BY created_at DESC, pursuit_id DESC
LIMIT $5
"""


class PostgresPursuitSummaryLookup:
    """Postgres-backed implementation of the `PursuitSummaryLookup` port."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def list_pursuits(
        self,
        *,
        status: PursuitStatus | None,
        beamline: str | None,
        limit: int,
        cursor: str | None,
    ) -> PursuitSummaryPage:
        """Return one page of pursuits, newest first."""
        after = decode_cursor(cursor) if cursor is not None else None
        rows = await self._pool.fetch(
            _SELECT_SQL,
            None if status is None else status.value,
            beamline,
            after[0] if after is not None else None,
            after[1] if after is not None else None,
            limit + 1,
        )

        has_more = len(rows) > limit
        items = [_to_summary(row) for row in rows[:limit]]
        next_cursor = (
            encode_cursor(created_at=items[-1].created_at, item_id=items[-1].pursuit_id)
            if has_more and items
            else None
        )
        return PursuitSummaryPage(items=items, next_cursor=next_cursor)


def _to_summary(row: Any) -> PursuitSummary:
    raw_held_for = row["held_for"]
    return PursuitSummary(
        pursuit_id=row["pursuit_id"],
        actor_id=row["actor_id"],
        goal=row["goal"],
        beamline=row["beamline"],
        status=PursuitStatus(row["status"]),
        held_for=None if raw_held_for is None else RoundOutcome(raw_held_for),
        round_count=row["round_count"],
        created_at=row["created_at"],
        stopped_at=row["stopped_at"],
    )


__all__ = ["PostgresPursuitSummaryLookup"]
