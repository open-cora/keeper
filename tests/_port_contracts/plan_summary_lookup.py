"""Behaviour every `PlanSummaryLookup` adapter owes its callers.

The run lookup's contract, for the other aggregate, and the same reason
for existing: one side reads a table a worker maintains, the other folds
every stream, and nothing about the code on one resembles the other.

Two things differ from the run contract and both are about the filter.
A plan has one event, so there is no transition to check and no second
timestamp to watch move. And a name is not unique, deliberately, so the
several-matches case is not an edge here but the one the whole slice has
to get right.
"""

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID, uuid4

import pytest

from keeper.execution.aggregates.plan.state import PlanName
from keeper.execution.aggregates.plan.summary import PlanSummaryLookup
from keeper.infrastructure.projection.cursor import InvalidCursorError, encode_cursor


class PlanWriter(Protocol):
    """Put plans where the adapter under test will find them."""

    async def define(self, *, plan_id: UUID, name: PlanName, at: datetime) -> None:
        """Write a plan down."""
        ...


Check = Callable[[PlanSummaryLookup, PlanWriter], Awaitable[None]]
"""One behaviour, applied to whichever adapter the driver supplies."""

_EPOCH = datetime(2026, 3, 1, 9, 0, tzinfo=UTC)
"""A fixed instant the checks below count minutes from.

Fixed rather than `now`, so an ordering assertion reads as an ordering
rather than as arithmetic on the wall clock.
"""

_PAGE = 50
"""A limit wide enough that paging does not interfere with other checks."""


async def _one_plan(writer: PlanWriter, *, name: str, minute: int) -> UUID:
    plan_id = uuid4()
    await writer.define(
        plan_id=plan_id,
        name=PlanName(name),
        at=_EPOCH + timedelta(minutes=minute),
    )
    return plan_id


async def check_an_empty_read_model_returns_an_empty_page(
    lookup: PlanSummaryLookup, writer: PlanWriter
) -> None:
    _ = writer
    page = await lookup.list_plans(name=None, limit=_PAGE, cursor=None)
    assert page.items == []
    assert page.next_cursor is None


async def check_a_defined_plan_shows_with_its_name_and_the_time_it_was_written(
    lookup: PlanSummaryLookup, writer: PlanWriter
) -> None:
    plan_id = await _one_plan(writer, name="count", minute=0)

    page = await lookup.list_plans(name=None, limit=_PAGE, cursor=None)

    (summary,) = page.items
    assert summary.plan_id == plan_id
    assert summary.name == PlanName("count")
    assert summary.created_at == _EPOCH


async def check_a_name_filter_returns_only_the_plans_called_that(
    lookup: PlanSummaryLookup, writer: PlanWriter
) -> None:
    await _one_plan(writer, name="scan", minute=0)
    wanted = await _one_plan(writer, name="count", minute=1)

    page = await lookup.list_plans(name=PlanName("count"), limit=_PAGE, cursor=None)

    assert [summary.plan_id for summary in page.items] == [wanted]


async def check_a_name_filter_matching_nothing_returns_an_empty_page(
    lookup: PlanSummaryLookup, writer: PlanWriter
) -> None:
    await _one_plan(writer, name="count", minute=0)

    page = await lookup.list_plans(name=PlanName("absent"), limit=_PAGE, cursor=None)

    assert page.items == []
    assert page.next_cursor is None


async def check_two_plans_sharing_a_name_both_come_back(
    lookup: PlanSummaryLookup, writer: PlanWriter
) -> None:
    """The case this slice exists to be honest about. One routine
    constrained two ways is two plans, and a lookup that returned one of
    them would be choosing for the caller on the strength of an ordering
    nobody asked about."""
    first = await _one_plan(writer, name="count", minute=0)
    second = await _one_plan(writer, name="count", minute=1)

    page = await lookup.list_plans(name=PlanName("count"), limit=_PAGE, cursor=None)

    assert {summary.plan_id for summary in page.items} == {first, second}


async def check_a_name_filter_is_an_exact_match_and_not_a_prefix(
    lookup: PlanSummaryLookup, writer: PlanWriter
) -> None:
    """A prefix match would quietly widen every adapter's lookup, and an
    adapter resolving `count` would find `count_with_dark_frames` and run
    the wrong routine."""
    await _one_plan(writer, name="count_with_dark_frames", minute=0)

    page = await lookup.list_plans(name=PlanName("count"), limit=_PAGE, cursor=None)

    assert page.items == []


async def check_plans_come_back_newest_first(lookup: PlanSummaryLookup, writer: PlanWriter) -> None:
    oldest = await _one_plan(writer, name="a", minute=0)
    middle = await _one_plan(writer, name="b", minute=1)
    newest = await _one_plan(writer, name="c", minute=2)

    page = await lookup.list_plans(name=None, limit=_PAGE, cursor=None)

    assert [summary.plan_id for summary in page.items] == [newest, middle, oldest]


async def check_a_full_page_hands_back_a_cursor_that_continues_it(
    lookup: PlanSummaryLookup, writer: PlanWriter
) -> None:
    """Every plan exactly once across the pages, in one order. A boundary
    that repeated a row or dropped one would still satisfy a check that
    only counted them."""
    ids = [await _one_plan(writer, name=f"p{i}", minute=i) for i in range(5)]

    first = await lookup.list_plans(name=None, limit=2, cursor=None)
    second = await lookup.list_plans(name=None, limit=2, cursor=first.next_cursor)
    third = await lookup.list_plans(name=None, limit=2, cursor=second.next_cursor)

    assert third.next_cursor is None
    walked = [summary.plan_id for page in (first, second, third) for summary in page.items]
    assert walked == list(reversed(ids))


async def check_the_last_page_hands_back_no_cursor(
    lookup: PlanSummaryLookup, writer: PlanWriter
) -> None:
    """A page exactly as long as the limit is still the last page when
    nothing follows it."""
    await _one_plan(writer, name="a", minute=0)
    await _one_plan(writer, name="b", minute=1)

    page = await lookup.list_plans(name=None, limit=2, cursor=None)

    assert len(page.items) == 2
    assert page.next_cursor is None


async def check_a_cursor_narrows_within_a_filter(
    lookup: PlanSummaryLookup, writer: PlanWriter
) -> None:
    """Paging and filtering compose, which matters more here than on the
    run side: several plans under one name is the ordinary case, so the
    second page of them has to stay under that name."""
    await _one_plan(writer, name="other", minute=0)
    wanted = [await _one_plan(writer, name="count", minute=i) for i in (1, 2, 3)]

    first = await lookup.list_plans(name=PlanName("count"), limit=2, cursor=None)
    second = await lookup.list_plans(name=PlanName("count"), limit=2, cursor=first.next_cursor)

    walked = [summary.plan_id for page in (first, second) for summary in page.items]
    assert walked == list(reversed(wanted))


async def check_a_cursor_that_did_not_come_from_a_response_is_refused(
    lookup: PlanSummaryLookup, writer: PlanWriter
) -> None:
    _ = writer
    with pytest.raises(InvalidCursorError):
        await lookup.list_plans(name=None, limit=_PAGE, cursor="not-a-cursor")


async def check_a_cursor_past_the_end_returns_an_empty_page(
    lookup: PlanSummaryLookup, writer: PlanWriter
) -> None:
    await _one_plan(writer, name="count", minute=10)

    page = await lookup.list_plans(
        name=None,
        limit=_PAGE,
        cursor=encode_cursor(created_at=_EPOCH, item_id=UUID(int=0)),
    )

    assert page.items == []


CHECKS: tuple[Check, ...] = (
    check_an_empty_read_model_returns_an_empty_page,
    check_a_defined_plan_shows_with_its_name_and_the_time_it_was_written,
    check_a_name_filter_returns_only_the_plans_called_that,
    check_a_name_filter_matching_nothing_returns_an_empty_page,
    check_two_plans_sharing_a_name_both_come_back,
    check_a_name_filter_is_an_exact_match_and_not_a_prefix,
    check_plans_come_back_newest_first,
    check_a_full_page_hands_back_a_cursor_that_continues_it,
    check_the_last_page_hands_back_no_cursor,
    check_a_cursor_narrows_within_a_filter,
    check_a_cursor_that_did_not_come_from_a_response_is_refused,
    check_a_cursor_past_the_end_returns_an_empty_page,
)
"""Every check above. Hand-written; the drivers guard against omissions."""


def checks_defined_but_not_listed() -> frozenset[str]:
    """Check functions defined in this module that `CHECKS` leaves out.

    The tuple is the contract; a function absent from it runs nowhere.
    """
    listed = {check.__name__ for check in CHECKS}
    defined = {
        name for name, value in globals().items() if name.startswith("check_") and callable(value)
    }
    return frozenset(defined - listed)
