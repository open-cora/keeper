"""The long-poll's loop, without a socket or a database.

`await_a_dispatch` is the whole of what `wait` adds to the listing
route, and it is worth testing apart from FastAPI because what it
promises is a timing property: it answers as soon as something matches,
it gives up when the caller's wait runs out, and it never trusts the
wake-up signal to tell it what happened.

The signal is faked rather than driven, because the real one needs
Postgres and what is being checked here is the loop's behaviour when a
signal arrives, when one is missed, and when none comes at all.
"""

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from keeper.execution.aggregates.execution import ExecutionBeamline, ExecutionStatus
from keeper.execution.aggregates.execution.summary import ExecutionSummary, ExecutionSummaryPage
from keeper.execution.waiting import await_a_dispatch

pytestmark = pytest.mark.unit

_WHEN = datetime(2026, 9, 25, 9, 0, tzinfo=UTC)


def _page(*, empty: bool) -> ExecutionSummaryPage:
    if empty:
        return ExecutionSummaryPage(items=[], next_cursor=None)
    return ExecutionSummaryPage(
        items=[
            ExecutionSummary(
                execution_id=uuid4(),
                procedure_id=uuid4(),
                procedure_name="align_then_scan",
                beamline=ExecutionBeamline("2-bm"),
                step_count=2,
                reported_count=0,
                status=ExecutionStatus.DISPATCHED,
                created_at=_WHEN,
                updated_at=_WHEN,
            )
        ],
        next_cursor=None,
    )


_A_TICK = 0.01
"""How long the fake signal takes to fire.

Short enough that a test finishes and long enough that the loop is not a
hot spin, which is what returning instantly would make it. It stands in
for a notify arriving well inside the ceiling, which is the real case.
"""


class _Signal:
    """A wake-up source that fires quickly, and records what it was asked.

    `waits` is the timeout of each call, which is what the ceiling
    assertions read. The source always returns before that timeout, the
    way a notify does; a test that wants the timeout itself to elapse
    would be measuring `asyncio.sleep`.
    """

    def __init__(self) -> None:
        self.waits: list[float] = []

    async def wait(self, timeout_seconds: float) -> None:
        self.waits.append(timeout_seconds)
        await asyncio.sleep(min(timeout_seconds, _A_TICK))

    async def close(self) -> None:
        return None


def _reads(*pages: ExecutionSummaryPage) -> Callable[[], Awaitable[ExecutionSummaryPage]]:
    """A reader answering in order, repeating its last answer forever."""
    remaining = list(pages)

    async def read() -> ExecutionSummaryPage:
        return remaining.pop(0) if len(remaining) > 1 else remaining[0]

    return read


async def test_a_dispatch_arriving_during_the_wait_is_answered_without_waiting_it_out() -> None:
    """The point of the whole arrangement: the caller asked for thirty
    seconds and gets an answer as soon as there is one."""
    signal = _Signal()

    page = await await_a_dispatch(_reads(_page(empty=False)), signal, wait=30.0)

    assert page.items
    assert len(signal.waits) == 1


async def test_nothing_arriving_returns_an_empty_page_rather_than_raising() -> None:
    """A conductor that waited and found nothing is the ordinary case,
    which is most of what an idle beamline ever gets."""
    signal = _Signal()

    page = await await_a_dispatch(_reads(_page(empty=True)), signal, wait=0.05)

    assert page.items == []
    assert signal.waits, "it waited rather than answering immediately"


async def test_a_signal_that_fires_with_nothing_behind_it_does_not_end_the_wait() -> None:
    """The signal says look, never what is there.

    A notify wakes every held request at the beamline it names and at
    the three it does not, so a loop that returned on the signal would
    hand a conductor an empty page and a new connection on every
    dispatch anywhere.
    """
    signal = _Signal()

    page = await await_a_dispatch(
        _reads(_page(empty=True), _page(empty=True), _page(empty=False)), signal, wait=30.0
    )

    assert page.items
    assert len(signal.waits) == 3


async def test_no_single_wait_runs_for_the_callers_whole_request() -> None:
    """A notify arriving between a query and the wait after it is lost,
    which `waiting` says of both channels. The ceiling is what
    turns that from a dispatch nobody picks up into a slower pickup.

    Asked for thirty seconds and asserted on what each individual wait
    was given, which is the ceiling rather than the ask.
    """
    signal = _Signal()

    await await_a_dispatch(
        _reads(_page(empty=True), _page(empty=True), _page(empty=False)), signal, wait=30.0
    )

    assert signal.waits, "the loop waited at least once"
    assert max(signal.waits) <= 1.0, (
        "no single wait may run to the caller's full thirty seconds, or a lost "
        "notify would cost the whole request"
    )


async def test_a_wait_that_has_already_run_out_reads_once_and_answers() -> None:
    signal = _Signal()

    page = await await_a_dispatch(_reads(_page(empty=True)), signal, wait=0.0)

    assert page.items == []
    assert signal.waits == []
