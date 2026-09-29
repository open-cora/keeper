"""What wakes a held intake request when a dispatch becomes readable.

The work intake is a long-poll: something at a beamline asks for the
executions dispatched to it and nothing has taken up, and the request is
held open rather than answered empty. This is the signal that ends the
wait early.

## Why this is Execution's and not the chassis's

The mechanism is the chassis's, and all of it is there.
`ListenNotifyWakeup` takes the channel to listen on, and `await_a_row`
holds the query-wait-query loop that every held request runs.

What is Execution's is which channel, and the reason that channel exists
at all: `proj_execution_execution_summary` is this context's table and
the trigger that announces a row landing in it is in this context's
migration.

That split is the one the kernel's docstring draws. A bounded context
that needs an additional Postgres-backed thing builds it from the pool
rather than growing a field on the kernel, and a signal named for one
context's read model is exactly that.

## Why not the channel the projection worker uses

`events` fires when an event is appended, which is before the read model
can answer for it. A held request waking on that queries the summary
table while the worker is still inside the transaction that writes the
row, finds nothing, and waits again; no second notify on that channel is
coming, because applying a projection appends no event. The migration
that adds the trigger holds the long version.

## Nothing here is load-bearing for correctness

A notify arriving while no listener is connected is lost, and so is one
arriving between a reader's query and its wait. `long_poll` explains
what that costs and why it is only latency.

So a deployment with `projection_use_listen_notify` off, or one running
with no database at all, gets `PollOnlyWakeup` and a slower intake rather
than a broken one.
"""

import contextlib
from collections.abc import AsyncGenerator
from typing import Final

from keeper.infrastructure.kernel import Kernel
from keeper.infrastructure.logging import get_logger
from keeper.infrastructure.projection.wakeup import (
    ListenNotifyWakeup,
    PollOnlyWakeup,
    WakeupSource,
)
from keeper.infrastructure.settings import Settings

DISPATCH_NOTIFY_CHANNEL: Final = "execution_summary"
"""The channel the execution summary's insert trigger announces on.

Named for the table rather than for the intake, because the trigger
fires for every row that lands there and a second reader with another
question would wait on the same one.
"""

_log = get_logger(__name__)


@contextlib.asynccontextmanager
async def waiting_lifespan(deps: Kernel, settings: Settings) -> AsyncGenerator[WakeupSource]:
    """Hold the intake's wake-up source for the life of the application.

    A context manager rather than a value built in `wire_execution`
    because it owns a connection and has to give it back. It is entered
    beside the projection worker's lifespan, and for the same reason
    that one is: the source must be closed before the pool is, or the
    release races `pool.close()`.

    Falls back to `PollOnlyWakeup` with no pool or with LISTEN/NOTIFY
    switched off, which is what `app_env=test` runs. A held request
    there re-reads on a plain sleep, and no test asks it to: the one
    that passes a wait has work waiting already, so the first read
    answers and the loop is never entered.
    """
    source: WakeupSource = (
        ListenNotifyWakeup(deps.pool, channel=DISPATCH_NOTIFY_CHANNEL)
        if deps.pool is not None and settings.projection_use_listen_notify
        else PollOnlyWakeup()
    )
    _log.info(
        "execution.waiting.started",
        source=type(source).__name__,
        channel=DISPATCH_NOTIFY_CHANNEL,
    )
    try:
        yield source
    finally:
        await source.close()
        _log.info("execution.waiting.stopped")


__all__ = ["DISPATCH_NOTIFY_CHANNEL", "waiting_lifespan"]
