"""`drain_projections`: integration-test helper.

Synchronously advances every registered projection until each
bookmark catches up to the latest event of types it subscribes to,
OR raises `ProjectionDrainTimeoutError` if the deadline elapses
first.

Lets contract / integration tests assert against projection state
immediately after appending events without sprinkling
`asyncio.sleep(...)` and hoping. Also serves as the documented
escape hatch for in-process workflows that need synchronous
projection consistency (rare; should not become a regular pattern).

## Per-projection "subscribed head" semantics

Each projection has a "subscribed head": the maximum event
position whose `event_type` is in that projection's
`subscribed_event_types`. A projection is considered caught up
when its bookmark >= its subscribed head, NOT the global head.

This matters as soon as projections over different aggregates are
co-registered. A test that appends to one aggregate only would
otherwise leave the other projection's bookmark stuck at 0 forever,
because no event of its subscribed types exists yet, and the drain
helper would time out over a projection that is correctly idle.

## Caller obligation: appends must be committed before draining

The subscribed-head sample uses `MAX(position)` against the
events table without `pg_current_snapshot()` / xmin in-flight
exclusion that `advance_subscriber_once` applies (the canonical
`(transaction_id, position)` cursor pattern). For test callers
that `await` their command handler before invoking drain, this
is a no-op (the append's transaction has committed and is
visible). But callers that hold a separate connection with an
uncommitted append while calling drain may see a false-positive
"caught up" verdict before the in-flight event lands. Don't.
"""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false

import asyncio

import asyncpg

from keeper.infrastructure.projection.registry import ProjectionRegistry
from keeper.infrastructure.projection.worker import advance_subscriber_once

_SUBSCRIBED_HEAD_SQL = """
SELECT COALESCE(MAX(position), 0) FROM events WHERE event_type = ANY($1::text[])
"""

_BOOKMARK_POSITION_SQL = """
SELECT last_position FROM projection_bookmarks WHERE name = $1
"""


class ProjectionDrainTimeoutError(Exception):
    """Raised when `drain_projections` exceeds its deadline before all
    bookmarks catch up. Indicates a stuck projection (apply() raising
    on every retry, or events landing faster than the test can drain
    them)."""

    def __init__(
        self,
        *,
        deadline_seconds: float,
        subscribed_heads: dict[str, int],
        bookmarks: dict[str, int],
    ) -> None:
        super().__init__(
            f"drain_projections did not catch up within {deadline_seconds}s. "
            f"Subscribed heads: {subscribed_heads}; bookmarks: {bookmarks}"
        )
        self.deadline_seconds = deadline_seconds
        self.subscribed_heads = subscribed_heads
        self.bookmarks = bookmarks


async def drain_projections(
    pool: asyncpg.Pool,
    registry: ProjectionRegistry,
    *,
    deadline_seconds: float = 5.0,
    batch_size: int = 100,
) -> None:
    """Advance every registered projection until each bookmark reaches
    its subscribed head, or the deadline expires.

    The subscribed head is sampled once per outer loop iteration; if
    new events land mid-drain, they're caught on the next sample.
    """
    if registry.is_empty():
        return

    loop = asyncio.get_event_loop()
    deadline = loop.time() + deadline_seconds

    while True:
        async with pool.acquire() as conn:
            subscribed_heads: dict[str, int] = {}
            bookmarks: dict[str, int] = {}
            for projection in registry:
                subscribed = sorted(projection.subscribed_event_types)
                head = int(await conn.fetchval(_SUBSCRIBED_HEAD_SQL, subscribed))
                subscribed_heads[projection.name] = head
                row = await conn.fetchval(_BOOKMARK_POSITION_SQL, projection.name)
                bookmarks[projection.name] = int(row) if row is not None else 0

        behind = [
            projection
            for projection in registry
            if bookmarks[projection.name] < subscribed_heads[projection.name]
        ]
        if not behind:
            return

        if loop.time() >= deadline:
            raise ProjectionDrainTimeoutError(
                deadline_seconds=deadline_seconds,
                subscribed_heads=subscribed_heads,
                bookmarks=bookmarks,
            )

        # Advance every behind projection by one batch in parallel.
        await asyncio.gather(
            *[
                advance_subscriber_once(pool, projection, batch_size=batch_size)
                for projection in behind
            ]
        )


__all__ = ["ProjectionDrainTimeoutError", "drain_projections"]
