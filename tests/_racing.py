"""An event store that makes two concurrent callers reach the same fold.

Lives at the tests/ root rather than in one integration file because two
of them need it and the reasoning is the part worth having once. What it
holds is not code that was awkward to retype: it is the rule about where
the barrier may go, and getting that wrong deadlocks the suite rather
than failing it.

## What it is for

A slice that writes several streams in one append is claiming that the
loser of a race writes nothing at all. The way to test that claim is to
have two callers fold the same state, both decide a full set of events,
and both append at the same expected version.

`asyncio.gather` alone does not arrange it. Two coroutines against a real
pool interleave however the scheduler and the connections happen to fall,
and the common outcome is that the first finishes before the second
loads, so the second is refused by the domain before it composes
anything. That run passes whether the writes are one append or several,
which makes it a test of nothing.

## Where the barrier may go

On exactly one stream type that every racing caller loads exactly once.

Both halves matter. A stream only one caller reads leaves the other
waiting forever. A stream some caller reads twice has it wait twice
against a barrier sized for one pass, and the second wait never
completes. Neither shows up as a failing assertion; both hang.

So the caller names the stream, and the right one is the aggregate whose
version the append is checked against, since that is the one every racing
caller loads and the one whose fold they must agree on.
"""

import asyncio
from typing import Any
from uuid import UUID


class HeldAtTheLoad:
    """The real store, with every caller made to wait after one load.

    Delegates everything and adds one behaviour. Not a seam the source
    knows about: what it arranges is a state two real callers reach on
    their own often enough to matter, and cannot be relied on to reach on
    any given run.
    """

    def __init__(self, inner: Any, barrier: asyncio.Barrier, *, on: str) -> None:
        self._inner = inner
        self._barrier = barrier
        self._on = on

    async def load(self, stream_type: str, stream_id: UUID) -> Any:
        loaded = await self._inner.load(stream_type, stream_id)
        if stream_type == self._on:
            await self._barrier.wait()
        return loaded

    async def append(
        self, stream_type: str, stream_id: UUID, expected_version: int, events: Any
    ) -> int:
        appended: int = await self._inner.append(stream_type, stream_id, expected_version, events)
        return appended

    async def append_streams(self, streams: Any, *, conn: object | None = None) -> Any:
        return await self._inner.append_streams(streams, conn=conn)


__all__ = ["HeldAtTheLoad"]
