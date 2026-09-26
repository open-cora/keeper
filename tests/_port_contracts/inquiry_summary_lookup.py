"""Behaviour every `InquirySummaryLookup` adapter owes its callers.

The fifth summary contract, and the same reason for existing as the four
beside it: one side reads a table a worker maintains, the other folds every
stream, and nothing about the code on one resembles the other.

Two things are new here.

**The filter is a three-valued status, not a boolean and not an id.** The
proposal contract next door exercises a nullable boolean; this one has to
walk a record through three states and check the filter at each, because
the middle state is the one the whole read model was widened for.

**The status is derived twice, by two unrelated rules.** The in-memory side
reads it off the fold, which sets it from which events landed. The Postgres
side computes it from two nullable timestamps. Those are the same rule
written in two languages with no shared code, so the checks below assert
the status on every path rather than trusting either.

The case that separates them is an inquiry answered without ever being
claimed. The fold reaches Answered in one step, and the columns reach it
with `claimed_at` still null, so an adapter that derived the status by
asking "was it claimed" instead of "was it answered" passes every other
check here and fails that one.
"""

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID, uuid4

import pytest

from keeper.counsel.aggregates.inquiry.state import InquiryConclusion, InquiryStatus
from keeper.counsel.aggregates.inquiry.summary import InquirySummaryLookup
from keeper.infrastructure.projection.cursor import InvalidCursorError, encode_cursor


class InquiryWriter(Protocol):
    """Put inquiries where the adapter under test will find them."""

    async def make(
        self,
        *,
        inquiry_id: UUID,
        actor_id: UUID,
        execution_id: UUID,
        objective: str,
        execution_step_count: int,
        at: datetime,
    ) -> None:
        """Write a question down."""
        ...

    async def claim(self, *, inquiry_id: UUID, at: datetime) -> None:
        """Record that a thinker took it up."""
        ...

    async def answer(
        self,
        *,
        inquiry_id: UUID,
        conclusion: str,
        observed_step_count: int,
        execution_ended: bool,
        proposal_id: UUID | None,
        at: datetime,
    ) -> None:
        """Record what the thinker concluded, and how much it saw."""
        ...


Check = Callable[[InquirySummaryLookup, InquiryWriter], Awaitable[None]]
"""One behaviour, applied to whichever adapter the driver supplies."""

_EPOCH = datetime(2026, 3, 1, 9, 0, tzinfo=UTC)
"""A fixed instant the checks below count minutes from.

Fixed rather than `now`, so an ordering assertion reads as an ordering
rather than as arithmetic on the wall clock.
"""

_PAGE = 50
"""A limit wide enough that paging does not interfere with other checks."""

_STEPS = 6
"""How many steps the execution behind a test inquiry has.

More than one, so that a partial observation is expressible. Every check
that reports an observation boundary counts against this.
"""


async def _one_inquiry(
    writer: InquiryWriter,
    *,
    minute: int,
    actor_id: UUID | None = None,
    execution_id: UUID | None = None,
    objective: str = "find the edge",
) -> UUID:
    inquiry_id = uuid4()
    await writer.make(
        inquiry_id=inquiry_id,
        actor_id=actor_id or uuid4(),
        execution_id=execution_id or uuid4(),
        objective=objective,
        execution_step_count=_STEPS,
        at=_EPOCH + timedelta(minutes=minute),
    )
    return inquiry_id


async def check_an_empty_read_model_returns_an_empty_page(
    lookup: InquirySummaryLookup, writer: InquiryWriter
) -> None:
    _ = writer
    page = await lookup.list_inquiries(status=None, limit=_PAGE, cursor=None)
    assert page.items == []
    assert page.next_cursor is None


async def check_a_new_inquiry_shows_with_its_asker_execution_and_question(
    lookup: InquirySummaryLookup, writer: InquiryWriter
) -> None:
    actor_id, execution_id = uuid4(), uuid4()
    inquiry_id = await _one_inquiry(
        writer, minute=0, actor_id=actor_id, execution_id=execution_id, objective="is it converged"
    )

    page = await lookup.list_inquiries(status=None, limit=_PAGE, cursor=None)

    (summary,) = page.items
    assert summary.inquiry_id == inquiry_id
    assert summary.actor_id == actor_id
    assert summary.execution_id == execution_id
    assert summary.objective == "is it converged"
    assert summary.created_at == _EPOCH


async def check_a_new_inquiry_carries_the_step_count_and_no_answer(
    lookup: InquirySummaryLookup, writer: InquiryWriter
) -> None:
    """The denominator is there from the start and the numerator is not.

    That asymmetry is the observation boundary's whole shape: how much
    there was to see is known when the question is put, and how much was
    seen is not known until something answers.
    """
    await _one_inquiry(writer, minute=0)

    page = await lookup.list_inquiries(status=None, limit=_PAGE, cursor=None)

    (summary,) = page.items
    assert summary.execution_step_count == _STEPS
    assert summary.conclusion is None
    assert summary.observed_step_count is None
    assert summary.execution_ended is None
    assert summary.proposal_id is None
    assert summary.claimed_at is None
    assert summary.answered_at is None


async def check_a_new_inquiry_is_open(lookup: InquirySummaryLookup, writer: InquiryWriter) -> None:
    await _one_inquiry(writer, minute=0)

    page = await lookup.list_inquiries(status=None, limit=_PAGE, cursor=None)

    assert page.items[0].status is InquiryStatus.OPEN


async def check_a_claimed_inquiry_is_claimed_and_says_when(
    lookup: InquirySummaryLookup, writer: InquiryWriter
) -> None:
    inquiry_id = await _one_inquiry(writer, minute=0)
    claimed_at = _EPOCH + timedelta(minutes=5)
    await writer.claim(inquiry_id=inquiry_id, at=claimed_at)

    page = await lookup.list_inquiries(status=None, limit=_PAGE, cursor=None)

    (summary,) = page.items
    assert summary.status is InquiryStatus.CLAIMED
    assert summary.claimed_at == claimed_at
    assert summary.answered_at is None


async def check_an_answered_inquiry_carries_its_observation_boundary(
    lookup: InquirySummaryLookup, writer: InquiryWriter
) -> None:
    """The three answer columns arrive together or the row is unreadable.

    A conclusion without the boundary it was reached from is the thing
    this aggregate was widened to prevent, so an adapter that dropped
    either count would leave a verdict nobody can weigh.
    """
    inquiry_id = await _one_inquiry(writer, minute=0)
    answered_at = _EPOCH + timedelta(minutes=5)
    await writer.answer(
        inquiry_id=inquiry_id,
        conclusion=InquiryConclusion.STOP.value,
        observed_step_count=2,
        execution_ended=False,
        proposal_id=None,
        at=answered_at,
    )

    page = await lookup.list_inquiries(status=None, limit=_PAGE, cursor=None)

    (summary,) = page.items
    assert summary.status is InquiryStatus.ANSWERED
    assert summary.conclusion is InquiryConclusion.STOP
    assert summary.observed_step_count == 2
    assert summary.execution_ended is False
    assert summary.answered_at == answered_at


async def check_an_inquiry_claimed_and_then_answered_is_answered(
    lookup: InquirySummaryLookup, writer: InquiryWriter
) -> None:
    """The other state that separates the two derivations, and the one a
    mutation caught this suite missing.

    Both timestamps are set here, so a read side that asks "was it
    claimed" before "was it answered" reports Claimed and passes every
    other check in this file: the filters still put the row on the right
    side, because they test the columns rather than this word.
    """
    inquiry_id = await _one_inquiry(writer, minute=0)
    await writer.claim(inquiry_id=inquiry_id, at=_EPOCH + timedelta(minutes=1))
    await writer.answer(
        inquiry_id=inquiry_id,
        conclusion=InquiryConclusion.STOP.value,
        observed_step_count=_STEPS,
        execution_ended=True,
        proposal_id=None,
        at=_EPOCH + timedelta(minutes=2),
    )

    page = await lookup.list_inquiries(status=None, limit=_PAGE, cursor=None)

    (summary,) = page.items
    assert summary.status is InquiryStatus.ANSWERED
    assert summary.claimed_at is not None


async def check_an_inquiry_answered_without_a_claim_is_answered(
    lookup: InquirySummaryLookup, writer: InquiryWriter
) -> None:
    """The state that separates the two derivations.

    Claiming is not a gate on answering, so this row reaches Answered with
    `claimed_at` still null. An adapter deriving the status from whether a
    thinker claimed it reports Open here and passes every other check.
    """
    inquiry_id = await _one_inquiry(writer, minute=0)
    await writer.answer(
        inquiry_id=inquiry_id,
        conclusion=InquiryConclusion.ABSTAIN.value,
        observed_step_count=_STEPS,
        execution_ended=True,
        proposal_id=None,
        at=_EPOCH + timedelta(minutes=1),
    )

    page = await lookup.list_inquiries(status=None, limit=_PAGE, cursor=None)

    (summary,) = page.items
    assert summary.status is InquiryStatus.ANSWERED
    assert summary.claimed_at is None


async def check_a_propose_answer_names_the_proposal_it_wrote(
    lookup: InquirySummaryLookup, writer: InquiryWriter
) -> None:
    """The join this aggregate adds, and the only arm that carries one."""
    inquiry_id = await _one_inquiry(writer, minute=0)
    proposal_id = uuid4()
    await writer.answer(
        inquiry_id=inquiry_id,
        conclusion=InquiryConclusion.PROPOSE.value,
        observed_step_count=_STEPS,
        execution_ended=True,
        proposal_id=proposal_id,
        at=_EPOCH + timedelta(minutes=1),
    )

    page = await lookup.list_inquiries(status=None, limit=_PAGE, cursor=None)

    (summary,) = page.items
    assert summary.conclusion is InquiryConclusion.PROPOSE
    assert summary.proposal_id == proposal_id


async def check_answering_does_not_move_when_the_question_was_asked(
    lookup: InquirySummaryLookup, writer: InquiryWriter
) -> None:
    """Three timestamps from two authorities, and the later two must not
    overwrite the first: a list is ordered by when a question was put."""
    inquiry_id = await _one_inquiry(writer, minute=0)
    await writer.claim(inquiry_id=inquiry_id, at=_EPOCH + timedelta(minutes=5))
    await writer.answer(
        inquiry_id=inquiry_id,
        conclusion=InquiryConclusion.REFER.value,
        observed_step_count=1,
        execution_ended=False,
        proposal_id=None,
        at=_EPOCH + timedelta(minutes=9),
    )

    page = await lookup.list_inquiries(status=None, limit=_PAGE, cursor=None)

    assert page.items[0].created_at == _EPOCH


async def check_the_open_filter_returns_only_questions_nothing_took_up(
    lookup: InquirySummaryLookup, writer: InquiryWriter
) -> None:
    waiting = await _one_inquiry(writer, minute=0)
    claimed = await _one_inquiry(writer, minute=1)
    await writer.claim(inquiry_id=claimed, at=_EPOCH + timedelta(minutes=2))

    page = await lookup.list_inquiries(status=InquiryStatus.OPEN, limit=_PAGE, cursor=None)

    assert [summary.inquiry_id for summary in page.items] == [waiting]


async def check_the_claimed_filter_returns_only_questions_being_thought_about(
    lookup: InquirySummaryLookup, writer: InquiryWriter
) -> None:
    """The staleness question, and the reason the filter is not a boolean.

    An answered-or-not flag folds this state in with the untouched ones,
    and this is the only state an operator hunting an abandoned thinker
    cares about.
    """
    await _one_inquiry(writer, minute=0)
    claimed = await _one_inquiry(writer, minute=1)
    await writer.claim(inquiry_id=claimed, at=_EPOCH + timedelta(minutes=2))
    answered = await _one_inquiry(writer, minute=3)
    await writer.answer(
        inquiry_id=answered,
        conclusion=InquiryConclusion.STOP.value,
        observed_step_count=_STEPS,
        execution_ended=True,
        proposal_id=None,
        at=_EPOCH + timedelta(minutes=4),
    )

    page = await lookup.list_inquiries(status=InquiryStatus.CLAIMED, limit=_PAGE, cursor=None)

    assert [summary.inquiry_id for summary in page.items] == [claimed]


async def check_the_answered_filter_returns_only_questions_something_came_back_to(
    lookup: InquirySummaryLookup, writer: InquiryWriter
) -> None:
    await _one_inquiry(writer, minute=0)
    claimed = await _one_inquiry(writer, minute=1)
    await writer.claim(inquiry_id=claimed, at=_EPOCH + timedelta(minutes=2))
    answered = await _one_inquiry(writer, minute=3)
    await writer.answer(
        inquiry_id=answered,
        conclusion=InquiryConclusion.STOP.value,
        observed_step_count=_STEPS,
        execution_ended=True,
        proposal_id=None,
        at=_EPOCH + timedelta(minutes=4),
    )

    page = await lookup.list_inquiries(status=InquiryStatus.ANSWERED, limit=_PAGE, cursor=None)

    assert [summary.inquiry_id for summary in page.items] == [answered]


async def check_no_filter_returns_every_state(
    lookup: InquirySummaryLookup, writer: InquiryWriter
) -> None:
    """The default, and the state a filter with no null would leave untested."""
    waiting = await _one_inquiry(writer, minute=0)
    claimed = await _one_inquiry(writer, minute=1)
    await writer.claim(inquiry_id=claimed, at=_EPOCH + timedelta(minutes=2))
    answered = await _one_inquiry(writer, minute=3)
    await writer.answer(
        inquiry_id=answered,
        conclusion=InquiryConclusion.STOP.value,
        observed_step_count=_STEPS,
        execution_ended=True,
        proposal_id=None,
        at=_EPOCH + timedelta(minutes=4),
    )

    page = await lookup.list_inquiries(status=None, limit=_PAGE, cursor=None)

    assert {summary.inquiry_id for summary in page.items} == {waiting, claimed, answered}


async def check_an_inquiry_walks_all_three_filters_as_it_progresses(
    lookup: InquirySummaryLookup, writer: InquiryWriter
) -> None:
    """One record moving between filters, which no other summary here does
    twice. A projection that wrote the second transition over the first,
    or forgot it, is visible only by walking the whole lifecycle."""
    inquiry_id = await _one_inquiry(writer, minute=0)
    while_open = await lookup.list_inquiries(status=InquiryStatus.OPEN, limit=_PAGE, cursor=None)

    await writer.claim(inquiry_id=inquiry_id, at=_EPOCH + timedelta(minutes=1))
    while_claimed = await lookup.list_inquiries(
        status=InquiryStatus.CLAIMED, limit=_PAGE, cursor=None
    )
    still_open = await lookup.list_inquiries(status=InquiryStatus.OPEN, limit=_PAGE, cursor=None)

    await writer.answer(
        inquiry_id=inquiry_id,
        conclusion=InquiryConclusion.STOP.value,
        observed_step_count=_STEPS,
        execution_ended=True,
        proposal_id=None,
        at=_EPOCH + timedelta(minutes=2),
    )
    once_answered = await lookup.list_inquiries(
        status=InquiryStatus.ANSWERED, limit=_PAGE, cursor=None
    )
    still_claimed = await lookup.list_inquiries(
        status=InquiryStatus.CLAIMED, limit=_PAGE, cursor=None
    )

    assert [summary.inquiry_id for summary in while_open.items] == [inquiry_id]
    assert [summary.inquiry_id for summary in while_claimed.items] == [inquiry_id]
    assert still_open.items == []
    assert [summary.inquiry_id for summary in once_answered.items] == [inquiry_id]
    assert still_claimed.items == []
    assert [
        while_open.items[0].status,
        while_claimed.items[0].status,
        once_answered.items[0].status,
    ] == [InquiryStatus.OPEN, InquiryStatus.CLAIMED, InquiryStatus.ANSWERED], (
        "the word on the row has to move with the filters, and it is derived "
        "separately from them on both sides"
    )


async def check_nothing_open_returns_an_empty_page(
    lookup: InquirySummaryLookup, writer: InquiryWriter
) -> None:
    """The honest answer when every question was taken up, and the one a
    thinker looking for work most needs to tell apart from an error."""
    claimed = await _one_inquiry(writer, minute=0)
    await writer.claim(inquiry_id=claimed, at=_EPOCH + timedelta(minutes=1))

    page = await lookup.list_inquiries(status=InquiryStatus.OPEN, limit=_PAGE, cursor=None)

    assert page.items == []
    assert page.next_cursor is None


async def check_inquiries_come_back_newest_first(
    lookup: InquirySummaryLookup, writer: InquiryWriter
) -> None:
    oldest = await _one_inquiry(writer, minute=0)
    middle = await _one_inquiry(writer, minute=1)
    newest = await _one_inquiry(writer, minute=2)

    page = await lookup.list_inquiries(status=None, limit=_PAGE, cursor=None)

    assert [summary.inquiry_id for summary in page.items] == [newest, middle, oldest]


async def check_a_full_page_hands_back_a_cursor_that_continues_it(
    lookup: InquirySummaryLookup, writer: InquiryWriter
) -> None:
    for minute in range(3):
        await _one_inquiry(writer, minute=minute)

    first = await lookup.list_inquiries(status=None, limit=2, cursor=None)
    assert first.next_cursor is not None
    second = await lookup.list_inquiries(status=None, limit=2, cursor=first.next_cursor)

    walked = [summary.inquiry_id for page in (first, second) for summary in page.items]
    assert len(walked) == 3
    assert len(set(walked)) == 3


async def check_the_last_page_hands_back_no_cursor(
    lookup: InquirySummaryLookup, writer: InquiryWriter
) -> None:
    await _one_inquiry(writer, minute=0)

    page = await lookup.list_inquiries(status=None, limit=_PAGE, cursor=None)

    assert page.next_cursor is None


async def check_a_cursor_narrows_within_a_filter(
    lookup: InquirySummaryLookup, writer: InquiryWriter
) -> None:
    """Paging and filtering compose, rather than the second page forgetting
    which question was asked."""
    for minute in range(3):
        await _one_inquiry(writer, minute=minute)
    claimed = await _one_inquiry(writer, minute=3)
    await writer.claim(inquiry_id=claimed, at=_EPOCH + timedelta(minutes=4))

    first = await lookup.list_inquiries(status=InquiryStatus.OPEN, limit=2, cursor=None)
    assert first.next_cursor is not None
    second = await lookup.list_inquiries(
        status=InquiryStatus.OPEN, limit=2, cursor=first.next_cursor
    )

    walked = [summary.inquiry_id for page in (first, second) for summary in page.items]
    assert claimed not in walked
    assert len(walked) == 3


async def check_inquiries_made_at_one_instant_page_without_repeating_or_skipping(
    lookup: InquirySummaryLookup, writer: InquiryWriter
) -> None:
    """The tie the id in the sort key exists for.

    As likely here as next door: the timestamp is this system's own clock,
    so an agent asking several questions in one turn lands them inside a
    single tick.
    """
    ids = {await _one_inquiry(writer, minute=0) for _ in range(4)}

    first = await lookup.list_inquiries(status=None, limit=2, cursor=None)
    assert first.next_cursor is not None
    second = await lookup.list_inquiries(status=None, limit=2, cursor=first.next_cursor)

    walked = [summary.inquiry_id for page in (first, second) for summary in page.items]
    assert len(walked) == 4
    assert set(walked) == ids


async def check_a_cursor_that_did_not_come_from_a_response_is_refused(
    lookup: InquirySummaryLookup, writer: InquiryWriter
) -> None:
    _ = writer
    with pytest.raises(InvalidCursorError):
        await lookup.list_inquiries(status=None, limit=_PAGE, cursor="not-a-cursor")


async def check_a_cursor_past_the_end_returns_an_empty_page(
    lookup: InquirySummaryLookup, writer: InquiryWriter
) -> None:
    await _one_inquiry(writer, minute=10)

    page = await lookup.list_inquiries(
        status=None,
        limit=_PAGE,
        cursor=encode_cursor(created_at=_EPOCH, item_id=uuid4()),
    )

    assert page.items == []
    assert page.next_cursor is None


CHECKS: tuple[Check, ...] = (
    check_an_empty_read_model_returns_an_empty_page,
    check_a_new_inquiry_shows_with_its_asker_execution_and_question,
    check_a_new_inquiry_carries_the_step_count_and_no_answer,
    check_a_new_inquiry_is_open,
    check_a_claimed_inquiry_is_claimed_and_says_when,
    check_an_answered_inquiry_carries_its_observation_boundary,
    check_an_inquiry_claimed_and_then_answered_is_answered,
    check_an_inquiry_answered_without_a_claim_is_answered,
    check_a_propose_answer_names_the_proposal_it_wrote,
    check_answering_does_not_move_when_the_question_was_asked,
    check_the_open_filter_returns_only_questions_nothing_took_up,
    check_the_claimed_filter_returns_only_questions_being_thought_about,
    check_the_answered_filter_returns_only_questions_something_came_back_to,
    check_no_filter_returns_every_state,
    check_an_inquiry_walks_all_three_filters_as_it_progresses,
    check_nothing_open_returns_an_empty_page,
    check_inquiries_come_back_newest_first,
    check_a_full_page_hands_back_a_cursor_that_continues_it,
    check_the_last_page_hands_back_no_cursor,
    check_a_cursor_narrows_within_a_filter,
    check_inquiries_made_at_one_instant_page_without_repeating_or_skipping,
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


__all__ = ["CHECKS", "Check", "InquiryWriter", "checks_defined_but_not_listed"]
