"""The long poll's timing property, against a real Postgres.

Everything else about the intake is proved with a faked signal, which
shows the loop does the right thing when woken. What no such test can
show is that anything wakes it, and that is the whole claim: a held
request answers in milliseconds rather than at its timeout.

The failure this exists to catch is silent. A held request listening to
the wrong channel, or to a channel nothing fires, still returns the
right rows and still passes every other test in the tree. It just
returns them thirty seconds late, and the only symptom is a conductor
that seems slow at a beamline nobody is timing.

## What is real here and what is not

Real: Postgres, the trigger, `LISTEN`/`NOTIFY`, the projection worker's
advance, and `await_a_dispatch` reading through the actual adapter.

Not real: HTTP. The route's contribution is parsing `wait` and calling
this function, which the contract tier already covers. Standing up a
server to assert a duration would add a second thing that can make the
measurement slow.

## The signal is tested apart from the loop, and that is the point

The obvious test, holding a whole intake request open and timing it,
passes whether or not anything wakes it. `await_a_dispatch` bounds each
wait at a second and re-queries after it, so a request with a dead
signal still finds the row on its next look, about a second late and
well inside any bound a loaded machine tolerates. That test would be
green with the channel misspelled.

So the first check below waits on the signal itself, with nothing else
in the way and a timeout long enough that a signal which never arrives
cannot be mistaken for a slow one. The loop checks that follow it are
about what the loop does with a wake-up, not about getting one.
"""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false

import asyncio
from datetime import UTC, datetime
from uuid import UUID, uuid4

import asyncpg
import pytest

from keeper.execution.adapters.postgres_execution_summary_lookup import (
    PostgresExecutionSummaryLookup,
)
from keeper.execution.aggregates.execution import ExecutionBeamline, ExecutionStatus
from keeper.execution.aggregates.execution.summary import ExecutionSummaryPage
from keeper.execution.projections.execution_summary import ExecutionSummaryProjection
from keeper.execution.waiting import DISPATCH_NOTIFY_CHANNEL, await_a_dispatch
from keeper.infrastructure.adapters.postgres_event_store import PostgresEventStore
from keeper.infrastructure.projection.wakeup import ListenNotifyWakeup
from keeper.infrastructure.projection.worker import advance_subscriber_once
from tests._port_contracts._writers import EventStoreExecutionWriter

pytestmark = [pytest.mark.integration]

_NEVER = 20.0
"""How long a wait that nothing answers would run for.

Only ever reached by a build where the signal is broken, so it is set
far above any latency a working one produces rather than near it.
"""

_WOKEN = 2.0
"""The bound a woken wait must come in under.

Generous by orders of magnitude against what a notify costs, because
this runs against a container on whatever machine is free. What matters
is the gap to `_NEVER`, which is the only other outcome.
"""

_LISTENING = 0.5
"""Long enough for a lazy `LISTEN` to be established before the insert.

`ListenNotifyWakeup` acquires its connection on the first `wait()`, and
a notify fired while nothing is listening is lost. Sleeping here is what
makes these tests about the trigger rather than about that race.
"""

_STEPS = ["move 2bmb:m1 to 0.0", "acquire tomo_scan"]


async def _read(pool: asyncpg.Pool, beamline: str) -> ExecutionSummaryPage:
    """The intake's query, through the adapter a deployment uses."""
    return await PostgresExecutionSummaryLookup(pool).list_executions(
        procedure_id=None,
        beamline=ExecutionBeamline(beamline),
        status=ExecutionStatus.DISPATCHED,
        limit=50,
        cursor=None,
    )


async def _dispatch_and_project(pool: asyncpg.Pool, *, beamline: str) -> UUID:
    """Append a dispatch and let the projection catch up, as the worker would.

    Draining here rather than running the worker keeps the test to one
    moving part. What fires the trigger is the projection's INSERT,
    whichever loop performs it.
    """
    execution_id = uuid4()
    await EventStoreExecutionWriter(PostgresEventStore(pool)).dispatch(
        execution_id=execution_id,
        procedure_id=uuid4(),
        steps=list(_STEPS),
        at=datetime.now(UTC),
        beamline=beamline,
    )
    while await advance_subscriber_once(pool, ExecutionSummaryProjection()):
        pass
    return execution_id


async def test_a_dispatch_landing_in_the_summary_table_wakes_a_listener(
    db_pool: asyncpg.Pool,
) -> None:
    """The claim the whole arrangement rests on, with nothing else in the way.

    A bare `wait` on the intake's channel, asked for twenty seconds,
    against a real trigger. It comes back in milliseconds or it does not
    come back at all, and there is no query in the picture that could
    find the row by another route and hide which happened.

    This is the check that fails if the channel is misspelled, if the
    trigger is missing from the migration, or if the trigger is put on
    `events` instead of on the table the intake reads.
    """
    signal = ListenNotifyWakeup(db_pool, channel=DISPATCH_NOTIFY_CHANNEL)
    loop = asyncio.get_running_loop()

    try:
        listening = asyncio.create_task(signal.wait(_NEVER))
        await asyncio.sleep(_LISTENING)
        assert not listening.done(), "the wait returned before anything had happened"

        started = loop.time()
        await _dispatch_and_project(db_pool, beamline=f"2-bm-{uuid4().hex[:8]}")
        await asyncio.wait_for(listening, timeout=_NEVER)
        elapsed = loop.time() - started
    finally:
        await signal.close()

    assert elapsed < _WOKEN, (
        f"the wait took {elapsed:.1f}s of {_NEVER}s, so nothing woke it and it ran to "
        "its timeout. The dispatch is in the table either way; what is broken is the "
        "signal, most likely a channel no trigger fires on."
    )


async def test_a_held_request_answers_with_the_work_the_signal_announced(
    db_pool: asyncpg.Pool,
) -> None:
    """The loop over the real signal and the real adapter, end to end.

    Not a timing assertion: the check above owns that claim, and this one
    would pass on a one-second re-query whether or not anything woke it.
    What it adds is that the rows a woken request answers with are the
    ones that landed, through the adapter a deployment uses.
    """
    beamline = f"2-bm-{uuid4().hex[:8]}"
    signal = ListenNotifyWakeup(db_pool, channel=DISPATCH_NOTIFY_CHANNEL)

    try:
        held = asyncio.create_task(
            await_a_dispatch(lambda: _read(db_pool, beamline), signal, _NEVER)
        )
        await asyncio.sleep(_LISTENING)
        assert not held.done(), "the request answered before there was anything to answer with"

        execution_id = await _dispatch_and_project(db_pool, beamline=beamline)
        page = await asyncio.wait_for(held, timeout=_NEVER)
    finally:
        await signal.close()

    assert [summary.execution_id for summary in page.items] == [execution_id]


async def test_a_dispatch_to_another_beamline_does_not_answer_this_request(
    db_pool: asyncpg.Pool,
) -> None:
    """Waking is not answering, which is the loop's other half.

    One trigger serves every beamline, so a held request wakes on work
    it must not take. It has to query, find nothing for itself, and go
    back to waiting rather than hand its caller another beamline's
    execution.
    """
    mine = f"2-bm-{uuid4().hex[:8]}"
    theirs = f"7-bm-{uuid4().hex[:8]}"
    signal = ListenNotifyWakeup(db_pool, channel=DISPATCH_NOTIFY_CHANNEL)

    try:
        held = asyncio.create_task(await_a_dispatch(lambda: _read(db_pool, mine), signal, 2.0))
        await asyncio.sleep(_LISTENING)

        await _dispatch_and_project(db_pool, beamline=theirs)
        page = await asyncio.wait_for(held, timeout=_NEVER)
    finally:
        await signal.close()

    assert page.items == [], "a request answered with an execution for another beamline"


async def test_work_already_waiting_is_returned_without_any_signal_at_all(
    db_pool: asyncpg.Pool,
) -> None:
    """The restart case, and the reason NOTIFY is never the source of truth.

    A conductor that was down while the dispatch landed hears no signal,
    because the notify fired when nothing was listening. It still has to
    get the work, and it does, because the first thing the loop does is
    query.
    """
    beamline = f"2-bm-{uuid4().hex[:8]}"
    execution_id = await _dispatch_and_project(db_pool, beamline=beamline)

    page = await _read(db_pool, beamline)

    assert [summary.execution_id for summary in page.items] == [execution_id]
