"""The long poll's timing property for Counsel, against a real Postgres.

Everything else about a held request is proved with a faked signal, which
shows the loop does the right thing when woken. What no such test can
show is that anything wakes it, and that is the whole claim: a held
request answers in milliseconds rather than at its timeout.

The failure this exists to catch is silent. A held request listening to
the wrong channel, or to a channel nothing fires, still returns the right
rows and still passes every other test in the tree. It just returns them
thirty seconds late, and the only symptom is a thinker that seems slow at
picking questions up, which nobody is timing.

This is the second of these, and the first is next door on the execution
summary. What the two do not share is the last check here: Execution's
trigger has one transition to care about and this one has three events
landing in the same table, only one of which puts a question into the
state a thinker is waiting for.

## What is real here and what is not

Real: Postgres, the trigger, `LISTEN`/`NOTIFY`, the projection's advance,
and `await_a_row` reading through the actual adapter.

Not real: HTTP. The route's contribution is parsing `wait` and calling
that function, which the contract tier already covers. Standing up a
server to assert a duration would add a second thing that can make the
measurement slow.

## The signal is tested apart from the loop, and that is the point

The obvious test, holding a whole request open and timing it, passes
whether or not anything wakes it. `await_a_row` bounds each wait at a
second and re-queries after it, so a request with a dead signal still
finds the row on its next look, about a second late and well inside any
bound a loaded machine tolerates. That test would be green with the
channel misspelled.

So the first check below waits on the signal itself, with nothing else in
the way and a timeout long enough that a signal which never arrives
cannot be mistaken for a slow one. The loop checks that follow it are
about what the loop does with a wake-up, not about getting one.
"""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false

import asyncio
from datetime import UTC, datetime
from uuid import UUID, uuid4

import asyncpg
import pytest

from keeper.counsel.adapters.postgres_inquiry_summary_lookup import (
    PostgresInquirySummaryLookup,
)
from keeper.counsel.aggregates.inquiry import InquiryStatus
from keeper.counsel.aggregates.inquiry.summary import InquirySummaryPage
from keeper.counsel.projections.inquiry_summary import PROJECTION_NAME, InquirySummaryProjection
from keeper.counsel.waiting import INQUIRY_NOTIFY_CHANNEL
from keeper.infrastructure.adapters.postgres_event_store import PostgresEventStore
from keeper.infrastructure.projection.long_poll import await_a_row
from keeper.infrastructure.projection.wakeup import ListenNotifyWakeup
from keeper.infrastructure.projection.worker import advance_subscriber_once
from tests._port_contracts._writers import EventStoreInquiryWriter

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

_ON_INSERT = 1 << 2
_ON_DELETE = 1 << 3
_ON_UPDATE = 1 << 4
"""Which events a trigger is armed for, as `pg_trigger.tgtype` packs them.

Postgres's own bit layout, written out because the catalog stores the
number and not the words. `pg_get_triggerdef` renders the same fact as
DDL and rides along in every failure message, so a reader never has to
decode a bitmask to see what went wrong.
"""

_LISTENING = 0.5
"""Long enough for a lazy `LISTEN` to be established before the insert.

`ListenNotifyWakeup` acquires its connection on the first `wait()`, and
a notify fired while nothing is listening is lost. Sleeping here is what
makes these tests about the trigger rather than about that race.
"""


async def _read(pool: asyncpg.Pool) -> InquirySummaryPage:
    """A waiting thinker's query, through the adapter a deployment uses.

    Narrowed to Open and to nothing else, which is the whole of what a
    thinker going looking asks for: an inquiry carries no beamline of
    its own, so there is no share of the questions that is this
    thinker's rather than another's.
    """
    return await PostgresInquirySummaryLookup(pool).list_inquiries(
        status=InquiryStatus.OPEN,
        limit=50,
        cursor=None,
    )


class _Questions:
    """Put questions and take them up, letting the projection catch up each time.

    One writer for the life of a test rather than one per call, because
    `EventStoreInquiryWriter` counts the versions it has written and a
    second writer would append a claim at the version the question
    already holds.

    Draining here rather than running the worker keeps a test to one
    moving part. What fires the trigger is the projection's INSERT,
    whichever loop performs it.
    """

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool
        self._writer = EventStoreInquiryWriter(PostgresEventStore(pool))
        self._projection = InquirySummaryProjection()

    async def ask(self) -> UUID:
        inquiry_id = uuid4()
        await self._writer.make(
            inquiry_id=inquiry_id,
            actor_id=uuid4(),
            execution_id=uuid4(),
            objective="is one scan enough",
            execution_step_count=2,
            at=datetime.now(UTC),
        )
        await self._drain()
        return inquiry_id

    async def claim(self, inquiry_id: UUID) -> None:
        """Take a question up, which is an UPDATE against the same table."""
        await self._writer.claim(inquiry_id=inquiry_id, at=datetime.now(UTC))
        await self._drain()

    async def _drain(self) -> None:
        while await advance_subscriber_once(self._pool, self._projection):
            pass


async def test_a_question_landing_in_the_summary_table_wakes_a_listener(
    db_pool: asyncpg.Pool,
) -> None:
    """The claim the whole arrangement rests on, with nothing else in the way.

    A bare `wait` on Counsel's channel, asked for twenty seconds,
    against a real trigger. It comes back in milliseconds or it does not
    come back at all, and there is no query in the picture that could
    find the row by another route and hide which happened.

    This is the check that fails if the channel is misspelled, if the
    trigger is missing from the migration, or if the trigger is put on
    `events` instead of on the table a thinker reads.
    """
    signal = ListenNotifyWakeup(db_pool, channel=INQUIRY_NOTIFY_CHANNEL)
    loop = asyncio.get_running_loop()
    try:
        waiting = asyncio.create_task(signal.wait(_NEVER))
        await asyncio.sleep(_LISTENING)

        started = loop.time()
        await _Questions(db_pool).ask()
        await waiting

        assert loop.time() - started < _WOKEN, (
            "the wait ran past what a notify costs, so nothing woke it and it "
            "was the twenty-second timeout that returned"
        )
    finally:
        await signal.close()


async def test_a_question_arriving_during_a_held_read_is_answered_without_waiting_it_out(
    db_pool: asyncpg.Pool,
) -> None:
    """The same signal, now with the loop and the real query behind it."""
    signal = ListenNotifyWakeup(db_pool, channel=INQUIRY_NOTIFY_CHANNEL)
    loop = asyncio.get_running_loop()
    try:
        held = asyncio.create_task(await_a_row(lambda: _read(db_pool), signal, _NEVER))
        await asyncio.sleep(_LISTENING)

        started = loop.time()
        asked = await _Questions(db_pool).ask()
        page = await held

        assert [item.inquiry_id for item in page.items] == [asked]
        assert loop.time() - started < _WOKEN
    finally:
        await signal.close()


async def test_the_trigger_announces_an_insert_and_neither_of_the_updates(
    db_pool: asyncpg.Pool,
) -> None:
    """The reason the trigger is AFTER INSERT and not AFTER INSERT OR UPDATE.

    A claim and an answer both move a question off Open, which is the
    state being waited for, so announcing them would wake every held
    request to tell it the work is gone. Three events land in this table
    and only the first is worth a notify.

    Asserted against the catalog rather than by waiting to see nothing
    arrive, which is what this test did first and what made it flake.
    A negative claim about a signal can only be timed out, and the
    margin between "not woken" and "woken" is whatever the machine is
    doing: the first version passed with 0.6ms to spare and failed on a
    loaded box. Worse, it could go green for the wrong reason, because a
    claim slow enough to outlast the window looks exactly like a claim
    that woke nothing.

    The definition settles it with no clock in the picture. Postgres
    will not fire an AFTER INSERT trigger on an UPDATE, so reading which
    events it is armed for proves the behaviour rather than sampling it.
    """
    rows: list[asyncpg.Record] = await db_pool.fetch(
        """
        SELECT tgtype, pg_get_triggerdef(oid) AS definition
        FROM pg_trigger
        WHERE tgrelid = $1::regclass AND NOT tgisinternal
        """,
        PROJECTION_NAME,
    )

    assert len(rows) == 1, f"expected one trigger on {PROJECTION_NAME}, found {len(rows)}"
    armed_for: int = rows[0]["tgtype"]
    definition: str = rows[0]["definition"]

    assert armed_for & _ON_INSERT, f"nothing announces a new question: {definition}"
    assert not armed_for & _ON_UPDATE, (
        "the trigger fires on UPDATE, so a claim or an answer wakes every waiting "
        f"thinker to tell it the work is gone: {definition}"
    )
    assert not armed_for & _ON_DELETE, (
        f"the trigger fires on DELETE, which announces a question that is not there: {definition}"
    )


async def test_a_question_already_open_is_answered_with_no_signal_at_all(
    db_pool: asyncpg.Pool,
) -> None:
    """Work that is already there needs no waking, and the route never
    reaches the loop for it. Here so the wake-up path is not the only
    way a question is ever found."""
    asked = await _Questions(db_pool).ask()

    page = await _read(db_pool)

    assert [item.inquiry_id for item in page.items] == [asked]
