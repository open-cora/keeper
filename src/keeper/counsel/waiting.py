"""What wakes a held request when a question becomes readable.

Something that thinks goes looking for work it was not handed: it asks
for the inquiries nobody has taken up, and the request is held open
rather than answered empty. This is the signal that ends the wait early.

## Why this is Counsel's and not the chassis's

The mechanism is the chassis's and all of it is there.
`ListenNotifyWakeup` takes the channel to listen on, and `await_a_row`
holds the loop every held request runs.

What is Counsel's is which channel, and the reason that channel exists:
`proj_counsel_inquiry_summary` is this context's table and the trigger
announcing a row landing in it is in this context's migration. Execution
has the same pair next door for the same reason, which is what made the
loop between them worth sharing and these two worth keeping apart.

## Why this context has one at all

The claim on an inquiry was built for the case where something goes
looking for work it was not handed, and the open listing is what that
something reads. Both halves were here before anything read them: the
partial index over unclaimed questions is in the same migration that
made the table.

What was missing was the wake-up. Without it a thinker learns that a
question exists by asking again, which is a request every few seconds,
almost all of them empty, and a pickup delay of half the interval.

## Nothing here is load-bearing for correctness

A notify arriving while no listener is connected is lost, and so is one
arriving between a reader's query and its wait. `long_poll` explains
what that costs and why it is only latency.

So a deployment with `projection_use_listen_notify` off, or one running
with no database at all, gets `PollOnlyWakeup` and a thinker that picks
work up more slowly rather than one that never does.
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

INQUIRY_NOTIFY_CHANNEL: Final = "counsel_inquiry_summary"
"""The channel the inquiry summary's insert trigger announces on.

Named for the table rather than for the reader, because the trigger
fires for every row that lands there and a second reader with another
question would wait on the same one.

Spelled out in full where the execution summary's is not, because the
two tables are one prefix apart and a channel named `inquiry_summary`
would read as the odd one rather than the matching one.
"""

_log = get_logger(__name__)


@contextlib.asynccontextmanager
async def waiting_lifespan(deps: Kernel, settings: Settings) -> AsyncGenerator[WakeupSource]:
    """Hold the reader's wake-up source for the life of the application.

    A context manager rather than a value built in `wire_counsel`
    because it owns a connection and has to give it back, and because
    `wire_counsel` is synchronous and returns a bundle. It is entered
    beside the projection worker's lifespan, and for the same reason
    that one is: the source must be closed before the pool is, or the
    release races `pool.close()`.

    Falls back to `PollOnlyWakeup` with no pool or with LISTEN/NOTIFY
    switched off, which is what `app_env=test` runs.
    """
    source: WakeupSource = (
        ListenNotifyWakeup(deps.pool, channel=INQUIRY_NOTIFY_CHANNEL)
        if deps.pool is not None and settings.projection_use_listen_notify
        else PollOnlyWakeup()
    )
    _log.info(
        "counsel.waiting.started",
        source=type(source).__name__,
        channel=INQUIRY_NOTIFY_CHANNEL,
    )
    try:
        yield source
    finally:
        await source.close()
        _log.info("counsel.waiting.stopped")


__all__ = ["INQUIRY_NOTIFY_CHANNEL", "waiting_lifespan"]
