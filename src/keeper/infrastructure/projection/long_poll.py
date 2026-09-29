"""Holding a read open until it has something to answer with.

A listing route usually answers with whatever is there. Two of them answer
a caller that is not a person and is asking because that is how it learns
there is work: something at a beamline asks for the executions dispatched
to it, and something that thinks asks for the inquiries nobody has taken
up. Both ask continuously, and answered the ordinary way that is a poll,
almost all of it empty, with a pickup delay of half the interval.

This is what those routes use instead. The read is repeated until it has
something or until the caller's wait runs out, and a signal decides when
to repeat it rather than what to answer.

## Why this is the chassis's and the channel is not

`execution/waiting.py` drew this line before there was a second caller to
force it: a bounded context owns which channel it listens on and the
reason that channel exists, because a channel is named for that context's
own table and announced by a trigger in that context's own migration. The
mechanism is shared. `ListenNotifyWakeup` beside this already was.

The loop sat in Execution anyway, which contradicted the argument in the
same file that made it. Counsel wanting the same loop over a different
page is what settles it, and what moves here is the part worth having one
of: the ceiling on a single wait, the rule that the query answers, and
returning an empty page rather than raising when nothing came.

## The signal is an optimization and the query is the truth

A notify carries no rows and can be missed. One arriving while no
listener is connected is gone, and so is one arriving between a reader's
query and its wait. So each wait is itself bounded and the query runs
again after it, which makes a missed signal cost latency until the next
look rather than work nobody picks up. Whatever this does, the work sits
durably in its table and the next read finds it.

Nothing here is load-bearing for correctness, and a deployment with
LISTEN/NOTIFY switched off or no database at all gets a slower intake
rather than a broken one.
"""

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from typing import Final, Protocol

from keeper.infrastructure.projection.wakeup import WakeupSource

SIGNAL_CEILING_SECONDS: Final = 1.0
"""How long one wait inside a held request may last before looking again.

The signal can be missed, so this is the bound on what a miss costs.

It is not the projection worker's poll interval and should not be tied to
it. That one governs how stale a read model may get with nobody asking,
and this one governs how long somebody actively waiting keeps waiting
after a lost notify. The two answer to different pressures and the
numbers happening to be close would not make them one setting.
"""


class Page(Protocol):
    """A page of a listing, as this loop reads one.

    One member, because one is all the loop looks at: whether anything
    matched. What is on the page is the caller's business and travels
    back untouched.

    A Protocol rather than a base class, so a context's page stays a
    plain frozen dataclass that knows nothing about being waited on.
    """

    @property
    def items(self) -> Sequence[object]: ...


async def await_a_row[PageT: Page](
    read: Callable[[], Awaitable[PageT]],
    signal: WakeupSource,
    wait: float,
) -> PageT:
    """Re-read until something matches or the caller's wait runs out.

    Query, wait, query again, and never wait-and-report-what-the-signal-said.
    A notify carries no rows and can be missed entirely, so the query is
    what answers and the signal only decides when to run it.

    The page comes back as whatever type went in, so a route keeps the
    page its own read port promised and this is generic without anything
    downstream having to widen.

    The loop's clock is the event loop's, not the domain clock on the
    kernel. What is being measured is how long a socket has been held,
    which is not a fact about the facility and has no business being
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
        await signal.wait(min(remaining, SIGNAL_CEILING_SECONDS))
        page = await read()
        if page.items:
            return page


__all__ = ["SIGNAL_CEILING_SECONDS", "Page", "await_a_row"]
