"""Async background task that periodically prunes expired idempotency rows.

Mirrors the projection worker's lifespan pattern (`asyncio.create_task`
on entry, `task.cancel()` + suppressed-CancelledError await on exit).
Runs for the lifetime of the FastAPI app via composition in
`keeper.api.main`.

## When it runs

- Every `interval_seconds` (default 1 hour). Hourly is a safe lazy
  cadence: TTL is 24h by default, so a 1-hour pruner produces a
  table that's at most ~25 hours old. Tighter cadences are
  available via override; higher pressure scenarios should use
  pg_cron or partition-by-day instead (deferred).

## When it skips

- `settings.idempotency_ttl_hours == 0`: the user has opted out of
  pruning entirely (forensic deployments, or legitimate desire to
  retain idempotency state forever).
- `deps.pool is None`: the in-memory test adapter doesn't need a
  background pruner; tests that care about expiry call `prune()`
  directly.

## Failure handling

A failed `store.prune()` call (DB hiccup, connection drop) is
logged and the loop continues; the next tick retries. Only
`CancelledError` (from lifespan shutdown) breaks the loop.
"""

import asyncio
import contextlib
from collections.abc import AsyncGenerator

from keeper.infrastructure.kernel import Kernel
from keeper.infrastructure.logging import get_logger

_log = get_logger(__name__)

_DEFAULT_INTERVAL_SECONDS = 3600.0


@contextlib.asynccontextmanager
async def idempotency_pruner_lifespan(
    deps: Kernel,
    *,
    interval_seconds: float = _DEFAULT_INTERVAL_SECONDS,
) -> AsyncGenerator[None]:
    """Spawn the idempotency pruner for the duration of the context.

    No-op when `settings.idempotency_ttl_hours == 0` or
    `deps.pool is None`.
    """
    ttl_hours = deps.settings.idempotency_ttl_hours
    if ttl_hours <= 0 or deps.pool is None:
        _log.info(
            "idempotency_pruner.skipped",
            reason="ttl=0" if ttl_hours <= 0 else "no pool",
        )
        yield
        return

    _log.info(
        "idempotency_pruner.started",
        ttl_hours=ttl_hours,
        interval_seconds=interval_seconds,
    )
    task = asyncio.create_task(
        _prune_loop(deps, ttl_hours, interval_seconds),
        name="idempotency-pruner",
    )
    try:
        yield
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        _log.info("idempotency_pruner.stopped")


async def _prune_loop(
    deps: Kernel,
    ttl_hours: int,
    interval_seconds: float,
) -> None:
    """Periodic prune loop. Logs on every successful prune (with row
    count) and on every failure (with traceback)."""
    while True:
        try:
            n = await deps.idempotency_store.prune(ttl_hours=ttl_hours)
            if n > 0:
                _log.info("idempotency_pruner.pruned", rows=n)
        except asyncio.CancelledError:
            raise
        except Exception:
            _log.exception("idempotency_pruner.failed")
        await asyncio.sleep(interval_seconds)


__all__ = ["idempotency_pruner_lifespan"]
