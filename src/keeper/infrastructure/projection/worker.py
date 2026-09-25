"""ProjectionWorker: advances every registered Projection along the event stream.

One asyncio task per projection inside an `asyncio.TaskGroup`. Each
task runs an independent advance loop:

  1. Read bookmark (FOR UPDATE).
  2. Run the canonical Khyst+Dudycz advance query: events with
     `(transaction_id, position) > bookmark` AND `transaction_id <
     pg_snapshot_xmin(...)` (in-flight exclusion) AND
     `event_type = ANY(subscribed_types)`, ORDER BY (transaction_id,
     position), LIMIT batch_size.
  3. Call `apply(event, conn)` per row.
  4. Update bookmark to the last processed (transaction_id, position).
  5. Commit. If anything raised, the entire batch rolls back and the
     bookmark stays put: at-least-once delivery on retry.

When a batch returns zero events, the loop sleeps via the WakeupSource
(LISTEN/NOTIFY or poll). Errors in the loop trigger exponential
backoff (1s -> 2s -> ... cap 60s) with a loud log; the loop never
silently skips an event.
"""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false

import asyncio
import contextlib
from typing import Any

import asyncpg

from keeper.infrastructure.logging import get_logger
from keeper.infrastructure.ports.event_store import StoredEvent
from keeper.infrastructure.projection.bookmark import (
    read_bookmark,
    write_bookmark,
    write_bookmark_failure,
)
from keeper.infrastructure.projection.registry import ProjectionRegistry
from keeper.infrastructure.projection.subscriber import DEFAULT_BATCH_SIZE, Subscriber
from keeper.infrastructure.projection.wakeup import WakeupSource

_log = get_logger(__name__)

# Khyst + Dudycz canonical advance query. Comparison is lexicographic
# `(transaction_id, position) > (last_tx, last_pos)`; in-flight
# exclusion uses `transaction_id < pg_snapshot_xmin(...)`. Uses the
# `events_advance_idx` (transaction_id, position) added in migration
# 20260512240000.
_ADVANCE_SQL = """
SELECT position, event_id, stream_type, stream_id, version, event_type,
       schema_version, payload, metadata, correlation_id, causation_id,
       principal_id, occurred_at, recorded_at,
       transaction_id::text AS transaction_id_text
FROM events
WHERE (transaction_id, position) > ($1::xid8, $2)
  AND transaction_id < pg_snapshot_xmin(pg_current_snapshot())
  AND event_type = ANY($3::text[])
ORDER BY transaction_id ASC, position ASC
LIMIT $4
"""

_BACKOFF_BASE_SECONDS = 1.0
_BACKOFF_MAX_SECONDS = 60.0


def _row_to_stored_event(row: Any) -> StoredEvent:
    """Mirror of postgres.event_store._row_to_event for the advance query.
    Duplicated rather than imported because the advance query has its
    own SELECT shape (transaction_id alias) that differs from the
    stream-load query.

    Both projections of the SELECT must surface every column on
    StoredEvent, otherwise subscribers see stale `None` values for
    fields that exist on the row but were dropped here. Keep the
    column lists in lock-step with `postgres.event_store._LOAD_SQL`
    when adding new envelope fields.
    """
    return StoredEvent(
        position=int(row["position"]),
        event_id=row["event_id"],
        stream_type=str(row["stream_type"]),
        stream_id=row["stream_id"],
        version=int(row["version"]),
        event_type=str(row["event_type"]),
        schema_version=int(row["schema_version"]),
        payload=row["payload"],
        metadata=row["metadata"],
        correlation_id=row["correlation_id"],
        causation_id=row["causation_id"],
        occurred_at=row["occurred_at"],
        recorded_at=row["recorded_at"],
        transaction_id=int(row["transaction_id_text"]),
        principal_id=row["principal_id"],
    )


async def advance_subscriber_once(
    pool: asyncpg.Pool,
    subscriber: Subscriber,
    *,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> int:
    """Advance one Subscriber by at most `batch_size` events. Returns
    the number of events processed (0 if the bookmark is already at
    the head of the visible-and-committed event stream).

    The whole batch, read-bookmark + apply-all + write-bookmark :
    runs in a single transaction so at-least-once delivery has clean
    semantics: either everything in the batch advances together, or
    nothing does.

    Callers from the worker pass the per-subscriber batch_size
    (`getattr(subscriber, "batch_size", DEFAULT_BATCH_SIZE)`); callers
    from the drain helper pass an explicit value to bound test cost.
    """
    subscribed = sorted(subscriber.subscribed_event_types)
    async with pool.acquire() as conn, conn.transaction():
        last_tx, last_pos = await read_bookmark(conn, subscriber.name)
        rows = await conn.fetch(
            _ADVANCE_SQL,
            last_tx,
            last_pos,
            subscribed,
            batch_size,
        )
        if not rows:
            return 0
        events = [_row_to_stored_event(row) for row in rows]
        for event in events:
            await subscriber.apply(event, conn)
        last = events[-1]
        await write_bookmark(
            conn,
            subscriber.name,
            last_transaction_id=last.transaction_id,
            last_position=last.position,
            last_event_recorded_at=last.recorded_at,
        )
    return len(events)


class ProjectionWorker:
    """Spawns one advance loop per registered projection."""

    def __init__(
        self,
        pool: asyncpg.Pool,
        registry: ProjectionRegistry,
        wakeup: WakeupSource,
        *,
        poll_interval_seconds: float = 5.0,
        batch_size: int = DEFAULT_BATCH_SIZE,
    ) -> None:
        self._pool = pool
        self._registry = registry
        self._wakeup = wakeup
        self._poll_interval_seconds = poll_interval_seconds
        # Per-subscriber default. Each Subscriber may declare its own
        # `batch_size` attribute (Reactions set this to 1); the loop
        # below reads `subscriber.batch_size` via getattr so the
        # worker-level value is the fallback only.
        self._batch_size = batch_size

    async def run(self) -> None:
        """Run advance loops until cancelled. Per-projection failures
        stay inside their own loop (caught + backed-off) so one
        misbehaving projection cannot bring the whole worker down.

        Empty-registry case is gated by `projection_worker_lifespan`
        which short-circuits before constructing the worker, so
        `TaskGroup` always has at least one task here.
        """
        async with asyncio.TaskGroup() as tg:
            for projection in self._registry:
                tg.create_task(
                    self._advance_loop(projection),
                    name=f"projection-advance:{projection.name}",
                )

    async def _advance_loop(self, projection: Subscriber) -> None:
        """Single projection's advance loop. Runs forever until
        cancelled."""
        backoff = _BACKOFF_BASE_SECONDS
        # Per-subscriber batch_size: Projections inherit the worker
        # default (100), Reactions override to 1 to avoid holding a
        # pool connection across a slow LLM call. Read once at loop
        # start since the class-level attribute is immutable per
        # subscriber instance.
        effective_batch_size = getattr(projection, "batch_size", self._batch_size)
        while True:
            try:
                processed = await advance_subscriber_once(
                    self._pool,
                    projection,
                    batch_size=effective_batch_size,
                )
                backoff = _BACKOFF_BASE_SECONDS  # reset on success
                if processed > 0:
                    _log.debug(
                        "projection.advance.batch",
                        projection=projection.name,
                        events=processed,
                    )
                else:
                    await self._wakeup.wait(self._poll_interval_seconds)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                _log.exception(
                    "projection.advance.error",
                    projection=projection.name,
                    backoff_seconds=backoff,
                )
                # persist failure state in a separate
                # small transaction so the operator can see "this
                # projection has failed N times since last success
                # with this error" without log-spelunking. If THIS
                # write itself fails we swallow it; we already logged
                # the original error and don't want failure-recording
                # to itself crash the loop.
                with contextlib.suppress(Exception):
                    await write_bookmark_failure(
                        self._pool,
                        projection.name,
                        error_message=str(exc),
                    )
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, _BACKOFF_MAX_SECONDS)


__all__ = ["ProjectionWorker", "advance_subscriber_once"]
