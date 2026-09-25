"""What wakes a held intake request when a dispatch becomes readable.

The work intake is a long-poll: something at a beamline asks for the
executions dispatched to it and nothing has taken up, and the request is
held open rather than answered empty. This is the signal that ends the
wait early.

## Why this is Execution's and not the chassis's

The mechanism is the chassis's. `ListenNotifyWakeup` already exists, is
already shared by every projection's advance loop, and takes the channel
to listen on. What is Execution's is which channel, and the reason that
channel exists at all: `proj_execution_execution_summary` is this
context's table and the trigger that announces a row landing in it is in
this context's migration.

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

A notify that arrives while no listener is connected is lost, and so is
one arriving between a reader's query and its wait. Both are true of the
projection worker's channel and are why it treats the advance query as
the source of truth. The intake does the same: it queries, waits with a
ceiling, and queries again. A missed signal costs latency until the next
look, never a dispatch nobody picks up, because the work sits durably at
`Dispatched` whatever this does.

So a deployment with `projection_use_listen_notify` off, or one running
with no database at all, gets `PollOnlyWakeup` and a slower intake rather
than a broken one.
"""

import asyncio
import contextlib
from collections.abc import AsyncGenerator, Awaitable, Callable
from typing import Final

from keeper.execution.aggregates.execution.summary import ExecutionSummaryPage
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

_SIGNAL_CEILING_SECONDS: Final = 1.0
"""How long one wait inside a held request may last before looking again.

The signal can be missed, so this is the bound on how long a miss costs.
It is not the projection worker's poll interval and should not be tied to
it: that one governs how stale a read model may get with nobody asking,
and this one governs how long somebody actively waiting keeps waiting
after a lost notify.
"""


async def await_a_dispatch(
    read: Callable[[], Awaitable[ExecutionSummaryPage]],
    signal: WakeupSource,
    wait: float,
) -> ExecutionSummaryPage:
    """Re-read until something matches or the caller's wait runs out.

    Query, wait, query again, never wait-and-report-what-the-signal-said.
    A notify carries no rows and can be missed entirely, so the query is
    what answers and the signal only decides when to run it.

    The loop's clock is the event loop's, not the domain clock on the
    kernel. What is being measured is how long a socket has been held,
    which is not a fact about the beamline and has no business being
    reported or replayed.

    Returns the last empty page on expiry rather than raising. A caller
    that waited and found nothing is in the ordinary case, not a failed
    one, and an empty page is what it asked for.
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + wait
    while True:
        remaining = deadline - loop.time()
        if remaining <= 0:
            return await read()
        await signal.wait(min(remaining, _SIGNAL_CEILING_SECONDS))
        page = await read()
        if page.items:
            return page


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
    switched off, which is what `app_env=test` runs. Every intake
    request in that environment passes no wait at all, so nothing
    sleeps.
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


__all__ = ["DISPATCH_NOTIFY_CHANNEL", "await_a_dispatch", "waiting_lifespan"]
