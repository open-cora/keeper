"""What wakes a held log read when an event becomes readable.

The log route is a long poll: a reader asks for what has happened since
the cursor it holds, and the request is held open rather than answered
empty. This is the signal that ends that wait early.

## Why this one may use the `events` channel, where the intakes may not

`keeper.execution.waiting` refuses this channel and is right to. A held
read of a projection waking on `events` queries a summary table while the
worker is still writing the row, finds nothing, and no second notify is
coming, because applying a projection appends no event.

This route reads `events` itself. The channel announces the table being
read, so the thing the reader is waiting for is the thing the signal
reports, and the objection does not transfer.

## What the in-flight exclusion costs, and why it is only latency

The read excludes transactions below `pg_snapshot_xmin`, so an event can
be committed and announced while an older open transaction still holds it
back. A reader woken by that notify queries and finds nothing, and no
further notify will come for that event.

`await_a_row` is what makes this survivable: every wait is bounded by
`SIGNAL_CEILING_SECONDS`, so the loop re-queries about once a second
whether or not a signal arrives. A premature wake costs a second of
latency and never a lost event.

## Nothing here is load-bearing for correctness

A notify arriving with no listener connected is lost, and so is one
arriving between a reader's query and its wait. The query is the truth
and the signal only decides when to run it, so a deployment with
`projection_use_listen_notify` off, or with no database at all, gets a
slower log read rather than a broken one.

One listener more on a channel that already exists, with its trigger
already firing. No migration, no second channel, and nothing added to the
plumbing a new channel would cost.
"""

import contextlib
from collections.abc import AsyncGenerator

from keeper.infrastructure.kernel import Kernel
from keeper.infrastructure.logging import get_logger
from keeper.infrastructure.projection.wakeup import (
    NOTIFY_CHANNEL,
    ListenNotifyWakeup,
    PollOnlyWakeup,
    WakeupSource,
)
from keeper.infrastructure.settings import Settings

_log = get_logger(__name__)


@contextlib.asynccontextmanager
async def log_waiting_lifespan(deps: Kernel, settings: Settings) -> AsyncGenerator[WakeupSource]:
    """Hold the log read's wake-up source for the life of the application.

    A context manager because it owns a connection and has to give it
    back, entered beside the projection worker's lifespan so it is closed
    before the pool is.

    Falls back to `PollOnlyWakeup` with no pool or with LISTEN/NOTIFY
    switched off, which is what `environment=test` runs.
    """
    source: WakeupSource = (
        ListenNotifyWakeup(deps.pool, channel=NOTIFY_CHANNEL)
        if deps.pool is not None and settings.projection_use_listen_notify
        else PollOnlyWakeup()
    )
    _log.info(
        "log.waiting.started",
        source=type(source).__name__,
        channel=NOTIFY_CHANNEL,
    )
    try:
        yield source
    finally:
        await source.close()
        _log.info("log.waiting.stopped")


__all__ = ["log_waiting_lifespan"]
