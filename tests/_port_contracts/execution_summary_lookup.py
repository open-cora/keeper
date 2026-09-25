"""Behaviour every `ExecutionSummaryLookup` adapter owes its callers.

The two implementations differ in kind, not only in mechanism. One reads
a table a background worker maintains; the other folds every execution stream
on every call because there is no table to read. Nothing about the code
on one side resembles the code on the other, so nothing but this file
makes "they answer alike" a checkable claim.

The gap is wider here than for runs, and the progress count is where it
sits. The fold counts the steps the evolver marked reported; the table
reads the size of a set the projection unioned into. Two routes to one
number, which is the thing most worth comparing.

Both drivers write through real execution events rather than seeding rows, so
the Postgres side exercises the projection as well as the query.
"""

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID, uuid4

import pytest

from keeper.execution.aggregates.execution.state import ExecutionBeamline, ExecutionStatus
from keeper.execution.aggregates.execution.summary import ExecutionSummaryLookup
from keeper.infrastructure.projection.cursor import InvalidCursorError, encode_cursor


class ExecutionWriter(Protocol):
    """Put executions where the adapter under test will find them.

    Four verbs, because four are enough to reach every column: a genesis
    sets everything, a claim and a step each move the status, and an
    ending moves it to its terminal.
    """

    async def dispatch(
        self,
        *,
        execution_id: UUID,
        procedure_id: UUID,
        steps: list[str],
        at: datetime,
        beamline: str = "2-bm",
    ) -> None:
        """Record an execution as dispatched, over these steps, to one beamline."""
        ...

    async def claim(self, *, execution_id: UUID, at: datetime) -> None:
        """Record that something took the execution up."""
        ...

    async def step(self, *, execution_id: UUID, index: int, at: datetime) -> None:
        """Record that the step at this index ended."""
        ...

    async def end(self, *, execution_id: UUID, at: datetime) -> None:
        """Record that nothing further is coming."""
        ...


Check = Callable[[ExecutionSummaryLookup, ExecutionWriter], Awaitable[None]]
"""One behaviour, applied to whichever adapter the driver supplies."""

_EPOCH = datetime(2026, 3, 1, 9, 0, tzinfo=UTC)
"""A fixed instant the checks below count minutes from.

Fixed rather than `now`, so an ordering assertion reads as an ordering
rather than as arithmetic on the wall clock, and so a failure prints the
same timestamps every run.
"""

_PAGE = 50
"""A limit wide enough that paging does not interfere with other checks."""

_STEPS = ["move 2bmb:m1 to 0.0", "acquire tomo_scan", "move 2bmb:m2 to 5.0"]


_PROCEDURE = uuid4()
"""The procedure most checks dispatch, when which one does not matter."""


async def _one_walk(
    writer: ExecutionWriter,
    *,
    minute: int,
    procedure_id: UUID | None = None,
    beamline: str = "2-bm",
) -> UUID:
    execution_id = uuid4()
    await writer.dispatch(
        execution_id=execution_id,
        procedure_id=procedure_id if procedure_id is not None else _PROCEDURE,
        steps=list(_STEPS),
        at=_EPOCH + timedelta(minutes=minute),
        beamline=beamline,
    )
    return execution_id


async def check_an_empty_read_model_returns_an_empty_page(
    lookup: ExecutionSummaryLookup, writer: ExecutionWriter
) -> None:
    _ = writer
    page = await lookup.list_executions(
        procedure_id=None, beamline=None, status=None, limit=_PAGE, cursor=None
    )
    assert page.items == []
    assert page.next_cursor is None


async def check_a_dispatched_walk_shows_its_steps_counted_and_none_reported(
    lookup: ExecutionSummaryLookup, writer: ExecutionWriter
) -> None:
    execution_id = await _one_walk(writer, minute=0)

    page = await lookup.list_executions(
        procedure_id=None, beamline=None, status=None, limit=_PAGE, cursor=None
    )

    (summary,) = page.items
    assert summary.execution_id == execution_id
    assert summary.procedure_id == _PROCEDURE
    assert summary.procedure_name == "align_then_scan"
    assert summary.beamline == ExecutionBeamline("2-bm")
    assert (summary.step_count, summary.reported_count) == (3, 0)
    assert summary.status is ExecutionStatus.DISPATCHED
    assert summary.created_at == _EPOCH
    assert summary.updated_at == _EPOCH


async def check_the_beamline_an_execution_was_dispatched_to_comes_back_with_it(
    lookup: ExecutionSummaryLookup, writer: ExecutionWriter
) -> None:
    """The column the work intake filters on, and the reason it is a copy.

    One adapter folds it out of a genesis payload and the other reads a
    column a projection wrote. A beamline that disagreed between the two
    would route work differently in a deployment than in a test, which
    is the class of divergence this whole suite exists to catch.
    """
    await _one_walk(writer, minute=0, beamline="7-bm")

    page = await lookup.list_executions(
        procedure_id=None, beamline=None, status=None, limit=_PAGE, cursor=None
    )

    (summary,) = page.items
    assert summary.beamline == ExecutionBeamline("7-bm")


async def check_a_beamline_filter_returns_only_the_work_of_that_beamline(
    lookup: ExecutionSummaryLookup, writer: ExecutionWriter
) -> None:
    """The half of the intake query that keeps beamlines apart.

    A conductor claiming another beamline's execution would drive
    hardware it does not own, and nothing downstream could undo it: a
    claim is a write and there is no command to take one back.
    """
    mine = await _one_walk(writer, minute=0, beamline="2-bm")
    await _one_walk(writer, minute=1, beamline="7-bm")

    page = await lookup.list_executions(
        procedure_id=None, beamline=ExecutionBeamline("2-bm"), status=None, limit=_PAGE, cursor=None
    )

    assert [summary.execution_id for summary in page.items] == [mine]


async def check_a_status_filter_returns_only_the_executions_in_it(
    lookup: ExecutionSummaryLookup, writer: ExecutionWriter
) -> None:
    """The other half. Dispatched is what nothing has taken up yet."""
    waiting = await _one_walk(writer, minute=0)
    taken = await _one_walk(writer, minute=1)
    await writer.claim(execution_id=taken, at=_EPOCH + timedelta(minutes=2))

    page = await lookup.list_executions(
        procedure_id=None,
        beamline=None,
        status=ExecutionStatus.DISPATCHED,
        limit=_PAGE,
        cursor=None,
    )

    assert [summary.execution_id for summary in page.items] == [waiting]


async def check_the_beamline_and_status_filters_narrow_together(
    lookup: ExecutionSummaryLookup, writer: ExecutionWriter
) -> None:
    """The intake's actual question, and the one an OR would get wrong.

    Three executions that each match one half and only one that matches
    both, so an adapter treating the pair as anything but an AND hands
    back more than one row and fails here.
    """
    wanted = await _one_walk(writer, minute=0, beamline="2-bm")
    await _one_walk(writer, minute=1, beamline="7-bm")
    claimed_here = await _one_walk(writer, minute=2, beamline="2-bm")
    await writer.claim(execution_id=claimed_here, at=_EPOCH + timedelta(minutes=3))

    page = await lookup.list_executions(
        procedure_id=None,
        beamline=ExecutionBeamline("2-bm"),
        status=ExecutionStatus.DISPATCHED,
        limit=_PAGE,
        cursor=None,
    )

    assert [summary.execution_id for summary in page.items] == [wanted]


async def check_a_beamline_filter_matching_nothing_returns_an_empty_page(
    lookup: ExecutionSummaryLookup, writer: ExecutionWriter
) -> None:
    """What an idle conductor gets, which is most of what it ever gets."""
    await _one_walk(writer, minute=0, beamline="2-bm")

    page = await lookup.list_executions(
        procedure_id=None,
        beamline=ExecutionBeamline("32-id"),
        status=ExecutionStatus.DISPATCHED,
        limit=_PAGE,
        cursor=None,
    )

    assert page.items == []
    assert page.next_cursor is None


async def check_claiming_a_walk_moves_it_off_dispatched(
    lookup: ExecutionSummaryLookup, writer: ExecutionWriter
) -> None:
    """The transient this status exists for. A row still at Dispatched
    with an old created_at says nothing ever took the work up, which is a
    different failure from a driver that died partway."""
    execution_id = await _one_walk(writer, minute=0)
    await writer.claim(execution_id=execution_id, at=_EPOCH + timedelta(minutes=1))

    page = await lookup.list_executions(
        procedure_id=None, beamline=None, status=None, limit=_PAGE, cursor=None
    )

    (summary,) = page.items
    assert summary.status is ExecutionStatus.CLAIMED
    assert summary.reported_count == 0


async def check_a_step_moves_a_claimed_walk_to_running(
    lookup: ExecutionSummaryLookup, writer: ExecutionWriter
) -> None:
    execution_id = await _one_walk(writer, minute=0)
    await writer.claim(execution_id=execution_id, at=_EPOCH + timedelta(minutes=1))
    await writer.step(execution_id=execution_id, index=0, at=_EPOCH + timedelta(minutes=2))

    page = await lookup.list_executions(
        procedure_id=None, beamline=None, status=None, limit=_PAGE, cursor=None
    )

    (summary,) = page.items
    assert summary.status is ExecutionStatus.RUNNING


async def check_a_step_on_an_unclaimed_walk_still_makes_it_running(
    lookup: ExecutionSummaryLookup, writer: ExecutionWriter
) -> None:
    """Claiming says who has the work; it is not a gate on reporting. A
    driver that skips it and reports a step has plainly started."""
    execution_id = await _one_walk(writer, minute=0)
    await writer.step(execution_id=execution_id, index=0, at=_EPOCH + timedelta(minutes=1))

    page = await lookup.list_executions(
        procedure_id=None, beamline=None, status=None, limit=_PAGE, cursor=None
    )

    (summary,) = page.items
    assert summary.status is ExecutionStatus.RUNNING


async def check_each_step_advances_the_count_and_leaves_the_start_alone(
    lookup: ExecutionSummaryLookup, writer: ExecutionWriter
) -> None:
    """The one column a replay could corrupt is the one nothing may touch
    twice, so it is asserted alongside the columns that must move."""
    execution_id = await _one_walk(writer, minute=0)
    await writer.step(execution_id=execution_id, index=0, at=_EPOCH + timedelta(minutes=1))
    await writer.step(execution_id=execution_id, index=1, at=_EPOCH + timedelta(minutes=2))

    page = await lookup.list_executions(
        procedure_id=None, beamline=None, status=None, limit=_PAGE, cursor=None
    )

    (summary,) = page.items
    assert (summary.step_count, summary.reported_count) == (3, 2)
    assert summary.created_at == _EPOCH
    assert summary.updated_at == _EPOCH + timedelta(minutes=2)


async def check_the_same_step_reported_twice_is_counted_once(
    lookup: ExecutionSummaryLookup, writer: ExecutionWriter
) -> None:
    """Delivery into a projection is at-least-once, so the count has to be
    a set and not a tally. A counter would report an execution further along
    than it is, which is the one lie a record of an abandoned execution must
    not tell."""
    execution_id = await _one_walk(writer, minute=0)
    await writer.step(execution_id=execution_id, index=0, at=_EPOCH + timedelta(minutes=1))
    await writer.step(execution_id=execution_id, index=0, at=_EPOCH + timedelta(minutes=1))

    page = await lookup.list_executions(
        procedure_id=None, beamline=None, status=None, limit=_PAGE, cursor=None
    )

    (summary,) = page.items
    assert summary.reported_count == 1


async def check_a_walk_can_end_with_steps_unreported(
    lookup: ExecutionSummaryLookup, writer: ExecutionWriter
) -> None:
    """The record a driver that died leaves behind. Both halves have to
    show the gap rather than close it."""
    execution_id = await _one_walk(writer, minute=0)
    await writer.step(execution_id=execution_id, index=0, at=_EPOCH + timedelta(minutes=1))
    await writer.end(execution_id=execution_id, at=_EPOCH + timedelta(minutes=2))

    page = await lookup.list_executions(
        procedure_id=None, beamline=None, status=None, limit=_PAGE, cursor=None
    )

    (summary,) = page.items
    assert summary.status is ExecutionStatus.ENDED
    assert (summary.reported_count, summary.step_count) == (1, 3)


async def check_a_filter_returns_only_the_walks_of_that_procedure(
    lookup: ExecutionSummaryLookup, writer: ExecutionWriter
) -> None:
    """The question the slice exists to answer: how did this routine go,
    every time it was run."""
    other = uuid4()
    await _one_walk(writer, minute=0, procedure_id=other)
    wanted = await _one_walk(writer, minute=1)

    page = await lookup.list_executions(
        procedure_id=_PROCEDURE, beamline=None, status=None, limit=_PAGE, cursor=None
    )

    assert [summary.execution_id for summary in page.items] == [wanted]


async def check_a_filter_matching_nothing_returns_an_empty_page(
    lookup: ExecutionSummaryLookup, writer: ExecutionWriter
) -> None:
    await _one_walk(writer, minute=0)

    page = await lookup.list_executions(
        procedure_id=uuid4(), beamline=None, status=None, limit=_PAGE, cursor=None
    )

    assert page.items == []
    assert page.next_cursor is None


async def check_every_walk_of_one_procedure_comes_back(
    lookup: ExecutionSummaryLookup, writer: ExecutionWriter
) -> None:
    """A routine composed once is walked every time it runs, so several
    rows under one procedure is the ordinary case and not a duplicate."""
    first = await _one_walk(writer, minute=0)
    second = await _one_walk(writer, minute=1)

    page = await lookup.list_executions(
        procedure_id=_PROCEDURE, beamline=None, status=None, limit=_PAGE, cursor=None
    )

    assert {summary.execution_id for summary in page.items} == {first, second}


async def check_executions_come_back_newest_first(
    lookup: ExecutionSummaryLookup, writer: ExecutionWriter
) -> None:
    oldest = await _one_walk(writer, minute=0)
    middle = await _one_walk(writer, minute=1)
    newest = await _one_walk(writer, minute=2)

    page = await lookup.list_executions(
        procedure_id=None, beamline=None, status=None, limit=_PAGE, cursor=None
    )

    assert [summary.execution_id for summary in page.items] == [newest, middle, oldest]


async def check_a_full_page_hands_back_a_cursor_that_continues_it(
    lookup: ExecutionSummaryLookup, writer: ExecutionWriter
) -> None:
    """Every execution exactly once across the pages, in one order. A boundary
    that repeated a row or dropped one would still satisfy a check that
    only counted them."""
    ids = [await _one_walk(writer, minute=i) for i in range(5)]

    first = await lookup.list_executions(
        procedure_id=None, beamline=None, status=None, limit=2, cursor=None
    )
    assert first.next_cursor is not None

    second = await lookup.list_executions(
        procedure_id=None, beamline=None, status=None, limit=2, cursor=first.next_cursor
    )
    assert second.next_cursor is not None

    third = await lookup.list_executions(
        procedure_id=None, beamline=None, status=None, limit=2, cursor=second.next_cursor
    )
    assert third.next_cursor is None

    walked = [summary.execution_id for page in (first, second, third) for summary in page.items]
    assert walked == list(reversed(ids))


async def check_the_last_page_hands_back_no_cursor(
    lookup: ExecutionSummaryLookup, writer: ExecutionWriter
) -> None:
    """A page exactly as long as the limit is still the last page when
    nothing follows it."""
    await _one_walk(writer, minute=0)
    await _one_walk(writer, minute=1)

    page = await lookup.list_executions(
        procedure_id=None, beamline=None, status=None, limit=2, cursor=None
    )

    assert len(page.items) == 2
    assert page.next_cursor is None


async def check_a_cursor_narrows_within_a_filter(
    lookup: ExecutionSummaryLookup, writer: ExecutionWriter
) -> None:
    """Paging and filtering compose. A second page that forgot the filter
    would return executions the first page had excluded."""
    await _one_walk(writer, minute=0, procedure_id=uuid4())
    wanted = [await _one_walk(writer, minute=i) for i in (1, 2, 3)]

    first = await lookup.list_executions(
        procedure_id=_PROCEDURE, beamline=None, status=None, limit=2, cursor=None
    )
    second = await lookup.list_executions(
        procedure_id=_PROCEDURE, beamline=None, status=None, limit=2, cursor=first.next_cursor
    )

    walked = [summary.execution_id for page in (first, second) for summary in page.items]
    assert walked == list(reversed(wanted))


async def check_a_cursor_that_did_not_come_from_a_response_is_refused(
    lookup: ExecutionSummaryLookup, writer: ExecutionWriter
) -> None:
    _ = writer
    with pytest.raises(InvalidCursorError):
        await lookup.list_executions(
            procedure_id=None, beamline=None, status=None, limit=_PAGE, cursor="not-a-cursor"
        )


async def check_a_cursor_past_the_end_returns_an_empty_page(
    lookup: ExecutionSummaryLookup, writer: ExecutionWriter
) -> None:
    """A well-formed cursor pointing before everything is not an error. It
    is a caller resuming an execution that has nothing left in it."""
    await _one_walk(writer, minute=10)

    page = await lookup.list_executions(
        procedure_id=None,
        beamline=None,
        status=None,
        limit=_PAGE,
        cursor=encode_cursor(created_at=_EPOCH, item_id=UUID(int=0)),
    )

    assert page.items == []


CHECKS: tuple[Check, ...] = (
    check_an_empty_read_model_returns_an_empty_page,
    check_a_dispatched_walk_shows_its_steps_counted_and_none_reported,
    check_the_beamline_an_execution_was_dispatched_to_comes_back_with_it,
    check_a_beamline_filter_returns_only_the_work_of_that_beamline,
    check_a_status_filter_returns_only_the_executions_in_it,
    check_the_beamline_and_status_filters_narrow_together,
    check_a_beamline_filter_matching_nothing_returns_an_empty_page,
    check_claiming_a_walk_moves_it_off_dispatched,
    check_a_step_moves_a_claimed_walk_to_running,
    check_a_step_on_an_unclaimed_walk_still_makes_it_running,
    check_each_step_advances_the_count_and_leaves_the_start_alone,
    check_the_same_step_reported_twice_is_counted_once,
    check_a_walk_can_end_with_steps_unreported,
    check_a_filter_returns_only_the_walks_of_that_procedure,
    check_a_filter_matching_nothing_returns_an_empty_page,
    check_every_walk_of_one_procedure_comes_back,
    check_executions_come_back_newest_first,
    check_a_full_page_hands_back_a_cursor_that_continues_it,
    check_the_last_page_hands_back_no_cursor,
    check_a_cursor_narrows_within_a_filter,
    check_a_cursor_that_did_not_come_from_a_response_is_refused,
    check_a_cursor_past_the_end_returns_an_empty_page,
)
"""Every behaviour in this contract, in the order they read best.

A tuple rather than discovery by name, so a check written and not listed
is a check nothing runs, and adding one is a deliberate act in two
places rather than an accident in one.
"""


def checks_defined_but_not_listed() -> frozenset[str]:
    """Check functions defined in this module that `CHECKS` leaves out.

    The tuple is the contract; a function absent from it runs nowhere.
    Deriving the other side from the module's own namespace means adding
    a check and forgetting to list it fails, rather than passing quietly
    with one behaviour fewer than the file appears to promise.
    """
    listed = {check.__name__ for check in CHECKS}
    defined = {
        name for name, value in globals().items() if name.startswith("check_") and callable(value)
    }
    return frozenset(defined - listed)


__all__ = ["CHECKS", "Check", "ExecutionWriter", "checks_defined_but_not_listed"]
