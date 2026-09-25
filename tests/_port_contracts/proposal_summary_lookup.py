"""Behaviour every `ProposalSummaryLookup` adapter owes its callers.

The fourth summary contract, and the same reason for existing as the
three beside it: one side reads a table a worker maintains, the other
folds every stream, and nothing about the code on one resembles the
other.

Two things are new here.

**The filter is a nullable boolean, not an id.** Three states rather
than two, so a check that only exercised true and false would leave the
unfiltered case, the default, untested on both sides.

**The aggregate has a second event.** Every other summary in this tree
is written once and never changes, or changes only a status word. This
one gains three columns when an acquisition takes the proposal, and the two
adapters reach that state by completely different routes: the Postgres
side runs an UPDATE the worker applied, the in-memory side folds the
second event. That a proposal moves from one side of the filter to the
other is the property most worth pinning, and it cannot be checked at
all on an aggregate with one event.
"""

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID, uuid4

import pytest

from keeper.counsel.aggregates.proposal.summary import ProposalSummaryLookup
from keeper.infrastructure.projection.cursor import InvalidCursorError, encode_cursor


class ProposalWriter(Protocol):
    """Put proposals where the adapter under test will find them."""

    async def make(
        self,
        *,
        proposal_id: UUID,
        actor_id: UUID,
        plan_id: UUID,
        at: datetime,
    ) -> None:
        """Write a proposal down."""
        ...

    async def take(
        self, *, proposal_id: UUID, execution_id: UUID, step_id: UUID, at: datetime
    ) -> None:
        """Record that one acquisition took it."""
        ...


Check = Callable[[ProposalSummaryLookup, ProposalWriter], Awaitable[None]]
"""One behaviour, applied to whichever adapter the driver supplies."""

_EPOCH = datetime(2026, 3, 1, 9, 0, tzinfo=UTC)
"""A fixed instant the checks below count minutes from.

Fixed rather than `now`, so an ordering assertion reads as an ordering
rather than as arithmetic on the wall clock.
"""

_PAGE = 50
"""A limit wide enough that paging does not interfere with other checks."""


async def _one_proposal(
    writer: ProposalWriter,
    *,
    minute: int,
    actor_id: UUID | None = None,
    plan_id: UUID | None = None,
) -> UUID:
    proposal_id = uuid4()
    await writer.make(
        proposal_id=proposal_id,
        actor_id=actor_id or uuid4(),
        plan_id=plan_id or uuid4(),
        at=_EPOCH + timedelta(minutes=minute),
    )
    return proposal_id


async def check_an_empty_read_model_returns_an_empty_page(
    lookup: ProposalSummaryLookup, writer: ProposalWriter
) -> None:
    _ = writer
    page = await lookup.list_proposals(is_open=None, limit=_PAGE, cursor=None)
    assert page.items == []
    assert page.next_cursor is None


async def check_a_new_proposal_shows_with_its_proposer_plan_and_time(
    lookup: ProposalSummaryLookup, writer: ProposalWriter
) -> None:
    actor_id, plan_id = uuid4(), uuid4()
    proposal_id = await _one_proposal(writer, minute=0, actor_id=actor_id, plan_id=plan_id)

    page = await lookup.list_proposals(is_open=None, limit=_PAGE, cursor=None)

    (summary,) = page.items
    assert summary.proposal_id == proposal_id
    assert summary.actor_id == actor_id
    assert summary.plan_id == plan_id
    assert summary.created_at == _EPOCH


async def check_a_new_proposal_has_no_acquisition_and_no_taken_time(
    lookup: ProposalSummaryLookup, writer: ProposalWriter
) -> None:
    """The null IS the status, so all three nulls have to survive the read."""
    await _one_proposal(writer, minute=0)

    page = await lookup.list_proposals(is_open=None, limit=_PAGE, cursor=None)

    (summary,) = page.items
    assert summary.execution_id is None
    assert summary.step_id is None
    assert summary.taken_at is None


async def check_a_taken_proposal_carries_the_acquisition_and_when_it_took_it(
    lookup: ProposalSummaryLookup, writer: ProposalWriter
) -> None:
    """Both halves of the reference, because either alone is unusable.

    A step id with no execution names an entity inside an aggregate
    nothing can reach, so an adapter that dropped one column would leave
    a row that reads as taken and cannot be followed.
    """
    proposal_id = await _one_proposal(writer, minute=0)
    execution_id = uuid4()
    step_id = uuid4()
    taken_at = _EPOCH + timedelta(minutes=5)
    await writer.take(
        proposal_id=proposal_id, execution_id=execution_id, step_id=step_id, at=taken_at
    )

    page = await lookup.list_proposals(is_open=None, limit=_PAGE, cursor=None)

    (summary,) = page.items
    assert (summary.execution_id, summary.step_id) == (execution_id, step_id)
    assert summary.taken_at == taken_at


async def check_taking_a_proposal_does_not_move_when_it_was_made(
    lookup: ProposalSummaryLookup, writer: ProposalWriter
) -> None:
    """Two timestamps from two authorities, and the second must not overwrite
    the first: a list is ordered by when a proposal was made."""
    proposal_id = await _one_proposal(writer, minute=0)
    await writer.take(
        proposal_id=proposal_id,
        execution_id=uuid4(),
        step_id=uuid4(),
        at=_EPOCH + timedelta(minutes=5),
    )

    page = await lookup.list_proposals(is_open=None, limit=_PAGE, cursor=None)

    assert page.items[0].created_at == _EPOCH


async def check_the_open_filter_returns_only_proposals_nothing_took(
    lookup: ProposalSummaryLookup, writer: ProposalWriter
) -> None:
    still_open = await _one_proposal(writer, minute=0)
    taken = await _one_proposal(writer, minute=1)
    await writer.take(
        proposal_id=taken, execution_id=uuid4(), step_id=uuid4(), at=_EPOCH + timedelta(minutes=2)
    )

    page = await lookup.list_proposals(is_open=True, limit=_PAGE, cursor=None)

    assert [summary.proposal_id for summary in page.items] == [still_open]


async def check_the_closed_filter_returns_only_proposals_an_acquisition_took(
    lookup: ProposalSummaryLookup, writer: ProposalWriter
) -> None:
    await _one_proposal(writer, minute=0)
    taken = await _one_proposal(writer, minute=1)
    await writer.take(
        proposal_id=taken, execution_id=uuid4(), step_id=uuid4(), at=_EPOCH + timedelta(minutes=2)
    )

    page = await lookup.list_proposals(is_open=False, limit=_PAGE, cursor=None)

    assert [summary.proposal_id for summary in page.items] == [taken]


async def check_no_filter_returns_both_sides(
    lookup: ProposalSummaryLookup, writer: ProposalWriter
) -> None:
    """The default, and the state a two-valued filter would leave untested."""
    still_open = await _one_proposal(writer, minute=0)
    taken = await _one_proposal(writer, minute=1)
    await writer.take(
        proposal_id=taken, execution_id=uuid4(), step_id=uuid4(), at=_EPOCH + timedelta(minutes=2)
    )

    page = await lookup.list_proposals(is_open=None, limit=_PAGE, cursor=None)

    assert {summary.proposal_id for summary in page.items} == {still_open, taken}


async def check_a_proposal_leaves_the_open_side_once_an_acquisition_takes_it(
    lookup: ProposalSummaryLookup, writer: ProposalWriter
) -> None:
    """The second event moving a row between filters, which is what this
    aggregate has and no other summary in the tree does."""
    proposal_id = await _one_proposal(writer, minute=0)
    before = await lookup.list_proposals(is_open=True, limit=_PAGE, cursor=None)

    await writer.take(
        proposal_id=proposal_id,
        execution_id=uuid4(),
        step_id=uuid4(),
        at=_EPOCH + timedelta(minutes=1),
    )
    after = await lookup.list_proposals(is_open=True, limit=_PAGE, cursor=None)

    assert [summary.proposal_id for summary in before.items] == [proposal_id]
    assert after.items == []


async def check_nothing_open_returns_an_empty_page(
    lookup: ProposalSummaryLookup, writer: ProposalWriter
) -> None:
    """The honest answer when every proposal was acted on, and the one a
    caller most needs to tell apart from an error."""
    taken = await _one_proposal(writer, minute=0)
    await writer.take(
        proposal_id=taken, execution_id=uuid4(), step_id=uuid4(), at=_EPOCH + timedelta(minutes=1)
    )

    page = await lookup.list_proposals(is_open=True, limit=_PAGE, cursor=None)

    assert page.items == []
    assert page.next_cursor is None


async def check_proposals_come_back_newest_first(
    lookup: ProposalSummaryLookup, writer: ProposalWriter
) -> None:
    oldest = await _one_proposal(writer, minute=0)
    middle = await _one_proposal(writer, minute=1)
    newest = await _one_proposal(writer, minute=2)

    page = await lookup.list_proposals(is_open=None, limit=_PAGE, cursor=None)

    assert [summary.proposal_id for summary in page.items] == [newest, middle, oldest]


async def check_a_full_page_hands_back_a_cursor_that_continues_it(
    lookup: ProposalSummaryLookup, writer: ProposalWriter
) -> None:
    for minute in range(3):
        await _one_proposal(writer, minute=minute)

    first = await lookup.list_proposals(is_open=None, limit=2, cursor=None)
    assert first.next_cursor is not None
    second = await lookup.list_proposals(is_open=None, limit=2, cursor=first.next_cursor)

    walked = [summary.proposal_id for page in (first, second) for summary in page.items]
    assert len(walked) == 3
    assert len(set(walked)) == 3


async def check_the_last_page_hands_back_no_cursor(
    lookup: ProposalSummaryLookup, writer: ProposalWriter
) -> None:
    await _one_proposal(writer, minute=0)

    page = await lookup.list_proposals(is_open=None, limit=_PAGE, cursor=None)

    assert page.next_cursor is None


async def check_a_cursor_narrows_within_a_filter(
    lookup: ProposalSummaryLookup, writer: ProposalWriter
) -> None:
    """Paging and filtering compose, rather than the second page forgetting
    which question was asked."""
    for minute in range(3):
        await _one_proposal(writer, minute=minute)
    taken = await _one_proposal(writer, minute=3)
    await writer.take(
        proposal_id=taken, execution_id=uuid4(), step_id=uuid4(), at=_EPOCH + timedelta(minutes=4)
    )

    first = await lookup.list_proposals(is_open=True, limit=2, cursor=None)
    assert first.next_cursor is not None
    second = await lookup.list_proposals(is_open=True, limit=2, cursor=first.next_cursor)

    walked = [summary.proposal_id for page in (first, second) for summary in page.items]
    assert taken not in walked
    assert len(walked) == 3


async def check_proposals_made_at_one_instant_page_without_repeating_or_skipping(
    lookup: ProposalSummaryLookup, writer: ProposalWriter
) -> None:
    """The tie the id in the sort key exists for.

    Likelier here than in the sibling contexts: a proposal's timestamp is
    this system's own clock, so an agent making several in one turn lands
    them inside a single tick.
    """
    ids = {await _one_proposal(writer, minute=0) for _ in range(4)}

    first = await lookup.list_proposals(is_open=None, limit=2, cursor=None)
    assert first.next_cursor is not None
    second = await lookup.list_proposals(is_open=None, limit=2, cursor=first.next_cursor)

    walked = [summary.proposal_id for page in (first, second) for summary in page.items]
    assert len(walked) == 4
    assert set(walked) == ids


async def check_a_cursor_that_did_not_come_from_a_response_is_refused(
    lookup: ProposalSummaryLookup, writer: ProposalWriter
) -> None:
    _ = writer
    with pytest.raises(InvalidCursorError):
        await lookup.list_proposals(is_open=None, limit=_PAGE, cursor="not-a-cursor")


async def check_a_cursor_past_the_end_returns_an_empty_page(
    lookup: ProposalSummaryLookup, writer: ProposalWriter
) -> None:
    await _one_proposal(writer, minute=10)

    page = await lookup.list_proposals(
        is_open=None,
        limit=_PAGE,
        cursor=encode_cursor(created_at=_EPOCH, item_id=uuid4()),
    )

    assert page.items == []
    assert page.next_cursor is None


CHECKS: tuple[Check, ...] = (
    check_an_empty_read_model_returns_an_empty_page,
    check_a_new_proposal_shows_with_its_proposer_plan_and_time,
    check_a_new_proposal_has_no_acquisition_and_no_taken_time,
    check_a_taken_proposal_carries_the_acquisition_and_when_it_took_it,
    check_taking_a_proposal_does_not_move_when_it_was_made,
    check_the_open_filter_returns_only_proposals_nothing_took,
    check_the_closed_filter_returns_only_proposals_an_acquisition_took,
    check_no_filter_returns_both_sides,
    check_a_proposal_leaves_the_open_side_once_an_acquisition_takes_it,
    check_nothing_open_returns_an_empty_page,
    check_proposals_come_back_newest_first,
    check_a_full_page_hands_back_a_cursor_that_continues_it,
    check_the_last_page_hands_back_no_cursor,
    check_a_cursor_narrows_within_a_filter,
    check_proposals_made_at_one_instant_page_without_repeating_or_skipping,
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


__all__ = ["CHECKS", "Check", "ProposalWriter", "checks_defined_but_not_listed"]
