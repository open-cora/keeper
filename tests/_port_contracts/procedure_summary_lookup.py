"""Behaviour every `ProcedureSummaryLookup` adapter owes its callers.

The plan lookup's contract, for the other authored aggregate, and the
same reason for existing: one side reads a table a worker maintains, the
other folds every stream, and nothing about the code on one resembles the
other.

One thing differs from the plan contract. A procedure carries a step
count, so there is a derived number the two sides have to agree on rather
than only fields copied off a payload. An in-memory adapter counts the
folded steps and a Postgres one reads a column a projection wrote, which
are two different ways to reach the same integer and exactly the kind of
divergence a shared suite is for.
"""

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID, uuid4

import pytest

from keeper.execution.aggregates.procedure.state import ProcedureBeamline, ProcedureName
from keeper.execution.aggregates.procedure.summary import ProcedureSummaryLookup
from keeper.infrastructure.projection.cursor import InvalidCursorError, encode_cursor


class ProcedureWriter(Protocol):
    """Put procedures where the adapter under test will find them."""

    async def define(
        self,
        *,
        procedure_id: UUID,
        name: ProcedureName,
        steps: int,
        at: datetime,
        beamline: str = "2-bm",
    ) -> None:
        """Compose a procedure of `steps` moves, for one beamline."""
        ...


Check = Callable[[ProcedureSummaryLookup, ProcedureWriter], Awaitable[None]]
"""One behaviour, applied to whichever adapter the driver supplies."""

_EPOCH = datetime(2026, 3, 1, 9, 0, tzinfo=UTC)
"""A fixed instant the checks below count minutes from.

Fixed rather than `now`, so an ordering assertion reads as an ordering
rather than as arithmetic on the wall clock.
"""

_PAGE = 50
"""A limit wide enough that paging does not interfere with other checks."""


async def _one_procedure(
    writer: ProcedureWriter,
    *,
    name: str,
    minute: int,
    steps: int = 1,
    beamline: str = "2-bm",
) -> UUID:
    procedure_id = uuid4()
    await writer.define(
        procedure_id=procedure_id,
        name=ProcedureName(name),
        steps=steps,
        at=_EPOCH + timedelta(minutes=minute),
        beamline=beamline,
    )
    return procedure_id


async def check_an_empty_read_model_returns_an_empty_page(
    lookup: ProcedureSummaryLookup, writer: ProcedureWriter
) -> None:
    _ = writer
    page = await lookup.list_procedures(name=None, limit=_PAGE, cursor=None)
    assert page.items == []
    assert page.next_cursor is None


async def check_a_defined_procedure_shows_with_its_name_and_the_time_it_was_written(
    lookup: ProcedureSummaryLookup, writer: ProcedureWriter
) -> None:
    procedure_id = await _one_procedure(writer, name="tomography", minute=0)

    page = await lookup.list_procedures(name=None, limit=_PAGE, cursor=None)

    (summary,) = page.items
    assert summary.procedure_id == procedure_id
    assert summary.name == ProcedureName("tomography")
    assert summary.created_at == _EPOCH


async def check_the_beamline_a_procedure_was_composed_for_comes_back_with_it(
    lookup: ProcedureSummaryLookup, writer: ProcedureWriter
) -> None:
    """The routing key, and it has to survive both routes into a summary.

    One adapter folds it out of a genesis payload and the other reads a
    column a projection wrote, so the two agreeing is not free. A
    dispatch of this procedure is routed on the copy of this value that
    lands on the execution, and a beamline that disagreed between the
    two adapters would route differently in a deployment than in a test.
    """
    await _one_procedure(writer, name="tomography", minute=0, beamline="7-bm")

    page = await lookup.list_procedures(name=None, limit=_PAGE, cursor=None)

    (summary,) = page.items
    assert summary.beamline == ProcedureBeamline("7-bm")


async def check_the_step_count_is_how_many_steps_were_composed(
    lookup: ProcedureSummaryLookup, writer: ProcedureWriter
) -> None:
    """The one derived column. One side counts a folded tuple and the
    other reads an integer a projection wrote, so agreeing here is not
    something either side gets for free."""
    await _one_procedure(writer, name="tomography", minute=0, steps=7)

    page = await lookup.list_procedures(name=None, limit=_PAGE, cursor=None)

    (summary,) = page.items
    assert summary.step_count == 7


async def check_a_name_filter_returns_only_the_procedures_called_that(
    lookup: ProcedureSummaryLookup, writer: ProcedureWriter
) -> None:
    await _one_procedure(writer, name="alignment", minute=0)
    wanted = await _one_procedure(writer, name="tomography", minute=1)

    page = await lookup.list_procedures(name=ProcedureName("tomography"), limit=_PAGE, cursor=None)

    assert [summary.procedure_id for summary in page.items] == [wanted]


async def check_a_name_filter_matching_nothing_returns_an_empty_page(
    lookup: ProcedureSummaryLookup, writer: ProcedureWriter
) -> None:
    await _one_procedure(writer, name="tomography", minute=0)

    page = await lookup.list_procedures(name=ProcedureName("absent"), limit=_PAGE, cursor=None)

    assert page.items == []
    assert page.next_cursor is None


async def check_two_procedures_sharing_a_name_both_come_back(
    lookup: ProcedureSummaryLookup, writer: ProcedureWriter
) -> None:
    """One routine composed two ways is two procedures, and a lookup that
    returned one of them would be choosing for the caller on the strength
    of an ordering nobody asked about."""
    first = await _one_procedure(writer, name="tomography", minute=0)
    second = await _one_procedure(writer, name="tomography", minute=1)

    page = await lookup.list_procedures(name=ProcedureName("tomography"), limit=_PAGE, cursor=None)

    assert {summary.procedure_id for summary in page.items} == {first, second}


async def check_a_name_filter_is_an_exact_match_and_not_a_prefix(
    lookup: ProcedureSummaryLookup, writer: ProcedureWriter
) -> None:
    """A prefix match would quietly widen every caller's lookup, and one
    resolving `tomography` would find `tomography_with_dark_frames` and
    dispatch the wrong routine."""
    await _one_procedure(writer, name="tomography_with_dark_frames", minute=0)

    page = await lookup.list_procedures(name=ProcedureName("tomography"), limit=_PAGE, cursor=None)

    assert page.items == []


async def check_procedures_come_back_newest_first(
    lookup: ProcedureSummaryLookup, writer: ProcedureWriter
) -> None:
    oldest = await _one_procedure(writer, name="a", minute=0)
    middle = await _one_procedure(writer, name="b", minute=1)
    newest = await _one_procedure(writer, name="c", minute=2)

    page = await lookup.list_procedures(name=None, limit=_PAGE, cursor=None)

    assert [summary.procedure_id for summary in page.items] == [newest, middle, oldest]


async def check_a_full_page_hands_back_a_cursor_that_continues_it(
    lookup: ProcedureSummaryLookup, writer: ProcedureWriter
) -> None:
    """Every procedure exactly once across the pages, in one order. A
    boundary that repeated a row or dropped one would still satisfy a
    check that only counted them."""
    ids = [await _one_procedure(writer, name=f"p{i}", minute=i) for i in range(5)]

    first = await lookup.list_procedures(name=None, limit=2, cursor=None)
    second = await lookup.list_procedures(name=None, limit=2, cursor=first.next_cursor)
    third = await lookup.list_procedures(name=None, limit=2, cursor=second.next_cursor)

    assert third.next_cursor is None
    walked = [summary.procedure_id for page in (first, second, third) for summary in page.items]
    assert walked == list(reversed(ids))


async def check_the_last_page_hands_back_no_cursor(
    lookup: ProcedureSummaryLookup, writer: ProcedureWriter
) -> None:
    """A page exactly as long as the limit is still the last page when
    nothing follows it."""
    await _one_procedure(writer, name="a", minute=0)
    await _one_procedure(writer, name="b", minute=1)

    page = await lookup.list_procedures(name=None, limit=2, cursor=None)

    assert len(page.items) == 2
    assert page.next_cursor is None


async def check_a_cursor_narrows_within_a_filter(
    lookup: ProcedureSummaryLookup, writer: ProcedureWriter
) -> None:
    """Paging and filtering compose, which matters here because several
    procedures under one name is an ordinary case, so the second page of
    them has to stay under that name."""
    await _one_procedure(writer, name="other", minute=0)
    wanted = [await _one_procedure(writer, name="tomography", minute=i) for i in (1, 2, 3)]

    first = await lookup.list_procedures(name=ProcedureName("tomography"), limit=2, cursor=None)
    second = await lookup.list_procedures(
        name=ProcedureName("tomography"), limit=2, cursor=first.next_cursor
    )

    walked = [summary.procedure_id for page in (first, second) for summary in page.items]
    assert walked == list(reversed(wanted))


async def check_a_cursor_that_did_not_come_from_a_response_is_refused(
    lookup: ProcedureSummaryLookup, writer: ProcedureWriter
) -> None:
    _ = writer
    with pytest.raises(InvalidCursorError):
        await lookup.list_procedures(name=None, limit=_PAGE, cursor="not-a-cursor")


async def check_a_cursor_past_the_end_returns_an_empty_page(
    lookup: ProcedureSummaryLookup, writer: ProcedureWriter
) -> None:
    await _one_procedure(writer, name="tomography", minute=10)

    page = await lookup.list_procedures(
        name=None,
        limit=_PAGE,
        cursor=encode_cursor(created_at=_EPOCH, item_id=UUID(int=0)),
    )

    assert page.items == []


CHECKS: tuple[Check, ...] = (
    check_an_empty_read_model_returns_an_empty_page,
    check_a_defined_procedure_shows_with_its_name_and_the_time_it_was_written,
    check_the_beamline_a_procedure_was_composed_for_comes_back_with_it,
    check_the_step_count_is_how_many_steps_were_composed,
    check_a_name_filter_returns_only_the_procedures_called_that,
    check_a_name_filter_matching_nothing_returns_an_empty_page,
    check_two_procedures_sharing_a_name_both_come_back,
    check_a_name_filter_is_an_exact_match_and_not_a_prefix,
    check_procedures_come_back_newest_first,
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
