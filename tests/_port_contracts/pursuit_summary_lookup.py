"""Behaviour every `PursuitSummaryLookup` adapter owes its callers.

The sixth summary contract, and the same reason for existing as the five
beside it: one side reads a table a worker maintains, the other folds every
stream, and nothing about the code on one resembles the other.

Two things are new here, and they are the two this suite is really for.

**The status is stored on one side and derived on the other.** Every
contract before this one had both adapters deriving from the same shape,
so the two spellings stayed close by construction. Here the fold sets a
status from which arm ran and the table holds one the projection wrote at
the time, and nothing but these checks makes them agree. Every check below
that moves a pursuit asserts the status afterwards, rather than trusting
either side to have got there.

**The status goes backwards.** Held becomes Running when somebody resumes,
and may become Held again on the next round. That is what stopped the
table using nullable timestamps the way its siblings do, and it is the
case that separates a correct adapter from one that assumed a lifecycle
only moves forward. The walk below holds a pursuit, resumes it, holds it
again and then withdraws it, checking the filter at every step.

The `held_for` reason rides along with the status and is checked with it,
because a page of held pursuits that could not say which of the two
conclusions held each one is a page a person cannot triage.
"""

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID, uuid4

import pytest

from keeper.infrastructure.projection.cursor import InvalidCursorError, encode_cursor
from keeper.pursuit.aggregates.pursuit.state import PursuitStatus, RoundOutcome
from keeper.pursuit.aggregates.pursuit.summary import PursuitSummaryLookup


class PursuitWriter(Protocol):
    """Put pursuits where the adapter under test will find them."""

    async def start(
        self,
        *,
        pursuit_id: UUID,
        actor_id: UUID,
        goal: str,
        beamline: str,
        at: datetime,
    ) -> None:
        """Write an authorization down."""
        ...

    async def open_round(self, *, pursuit_id: UUID, round_index: int, at: datetime) -> None:
        """Record that the loop turned."""
        ...

    async def close_round(
        self, *, pursuit_id: UUID, round_index: int, outcome: RoundOutcome, at: datetime
    ) -> None:
        """Record how the round ended, which is what moves the status."""
        ...

    async def resume(self, *, pursuit_id: UUID, at: datetime) -> None:
        """Record that a person put a held pursuit back to work."""
        ...

    async def withdraw(self, *, pursuit_id: UUID, at: datetime) -> None:
        """Record that a person revoked the authorization."""
        ...


Check = Callable[[PursuitSummaryLookup, PursuitWriter], Awaitable[None]]
"""One behaviour, applied to whichever adapter the driver supplies."""

_EPOCH = datetime(2026, 3, 1, 9, 0, tzinfo=UTC)
"""A fixed instant the checks below count minutes from.

Fixed rather than `now`, so an ordering assertion reads as an ordering
rather than as arithmetic on the wall clock.
"""

_PAGE = 50
"""A limit wide enough that paging does not interfere with other checks."""

_BEAMLINE = "2-bm"


async def _one_pursuit(
    writer: PursuitWriter,
    *,
    minute: int,
    actor_id: UUID | None = None,
    goal: str = "find the edge of the useful exposure range",
    beamline: str = _BEAMLINE,
) -> UUID:
    pursuit_id = uuid4()
    await writer.start(
        pursuit_id=pursuit_id,
        actor_id=actor_id or uuid4(),
        goal=goal,
        beamline=beamline,
        at=_EPOCH + timedelta(minutes=minute),
    )
    return pursuit_id


async def _a_round_ending(
    writer: PursuitWriter,
    pursuit_id: UUID,
    *,
    index: int,
    outcome: RoundOutcome,
    minute: int,
) -> None:
    await writer.open_round(
        pursuit_id=pursuit_id, round_index=index, at=_EPOCH + timedelta(minutes=minute)
    )
    await writer.close_round(
        pursuit_id=pursuit_id,
        round_index=index,
        outcome=outcome,
        at=_EPOCH + timedelta(minutes=minute + 1),
    )


async def _only(lookup: PursuitSummaryLookup, **narrow: object) -> list[UUID]:
    page = await lookup.list_pursuits(
        status=narrow.get("status"),  # pyright: ignore[reportArgumentType]
        beamline=narrow.get("beamline"),  # pyright: ignore[reportArgumentType]
        limit=_PAGE,
        cursor=None,
    )
    return [summary.pursuit_id for summary in page.items]


async def check_an_empty_read_model_returns_an_empty_page(
    lookup: PursuitSummaryLookup, writer: PursuitWriter
) -> None:
    _ = writer
    page = await lookup.list_pursuits(status=None, beamline=None, limit=_PAGE, cursor=None)

    assert page.items == []
    assert page.next_cursor is None


async def check_a_new_pursuit_shows_with_its_author_goal_and_beamline(
    lookup: PursuitSummaryLookup, writer: PursuitWriter
) -> None:
    """The three a person scanning a page reads. Without the goal the page
    is a list of identifiers; without the beamline it is a list nobody at
    one beamline can narrow."""
    author = uuid4()
    pursuit_id = await _one_pursuit(
        writer, minute=0, actor_id=author, goal="settle the exposure", beamline="7-bm"
    )

    page = await lookup.list_pursuits(status=None, beamline=None, limit=_PAGE, cursor=None)

    (only,) = page.items
    assert only.pursuit_id == pursuit_id
    assert only.actor_id == author
    assert only.goal == "settle the exposure"
    assert only.beamline == "7-bm"


async def check_a_new_pursuit_is_running_with_no_rounds_and_no_ending(
    lookup: PursuitSummaryLookup, writer: PursuitWriter
) -> None:
    await _one_pursuit(writer, minute=0)

    page = await lookup.list_pursuits(status=None, beamline=None, limit=_PAGE, cursor=None)

    (only,) = page.items
    assert only.status is PursuitStatus.RUNNING
    assert only.round_count == 0
    assert only.held_for is None
    assert only.stopped_at is None


async def check_opening_rounds_raises_the_count(
    lookup: PursuitSummaryLookup, writer: PursuitWriter
) -> None:
    pursuit_id = await _one_pursuit(writer, minute=0)
    await writer.open_round(pursuit_id=pursuit_id, round_index=0, at=_EPOCH)
    await writer.open_round(pursuit_id=pursuit_id, round_index=1, at=_EPOCH)

    page = await lookup.list_pursuits(status=None, beamline=None, limit=_PAGE, cursor=None)

    assert page.items[0].round_count == 2


async def check_an_advancing_round_leaves_the_pursuit_running(
    lookup: PursuitSummaryLookup, writer: PursuitWriter
) -> None:
    """The only outcome that does. A loop carries on while there is
    something to run."""
    pursuit_id = await _one_pursuit(writer, minute=0)
    await _a_round_ending(writer, pursuit_id, index=0, outcome=RoundOutcome.ADVANCED, minute=1)

    page = await lookup.list_pursuits(status=None, beamline=None, limit=_PAGE, cursor=None)

    (only,) = page.items
    assert only.status is PursuitStatus.RUNNING
    assert only.held_for is None


async def check_a_completing_round_stops_the_pursuit_without_an_ending_stamp(
    lookup: PursuitSummaryLookup, writer: PursuitWriter
) -> None:
    """`stopped_at` is set by a person withdrawing and by nothing else, so
    a pursuit that concluded its own objective has a stop with no stamp.
    Both sides have to agree on that, and it is the sort of asymmetry an
    adapter quietly smooths over."""
    pursuit_id = await _one_pursuit(writer, minute=0)
    await _a_round_ending(writer, pursuit_id, index=0, outcome=RoundOutcome.COMPLETED, minute=1)

    page = await lookup.list_pursuits(status=None, beamline=None, limit=_PAGE, cursor=None)

    (only,) = page.items
    assert only.status is PursuitStatus.STOPPED
    assert only.stopped_at is None


async def _held_by(
    lookup: PursuitSummaryLookup, writer: PursuitWriter, outcome: RoundOutcome
) -> None:
    pursuit_id = await _one_pursuit(writer, minute=0)
    await _a_round_ending(writer, pursuit_id, index=0, outcome=outcome, minute=1)

    page = await lookup.list_pursuits(status=None, beamline=None, limit=_PAGE, cursor=None)

    (only,) = page.items
    assert only.status is PursuitStatus.HELD
    assert only.held_for is outcome


async def check_a_stalled_round_holds_the_pursuit_and_says_so(
    lookup: PursuitSummaryLookup, writer: PursuitWriter
) -> None:
    await _held_by(lookup, writer, RoundOutcome.STALLED)


async def check_a_referred_round_holds_the_pursuit_and_says_so(
    lookup: PursuitSummaryLookup, writer: PursuitWriter
) -> None:
    """The reason a person triaging a page needs: this one is waiting for
    them, where a stalled one is waiting for data."""
    await _held_by(lookup, writer, RoundOutcome.REFERRED)


async def check_resuming_clears_the_hold_and_its_reason(
    lookup: PursuitSummaryLookup, writer: PursuitWriter
) -> None:
    pursuit_id = await _one_pursuit(writer, minute=0)
    await _a_round_ending(writer, pursuit_id, index=0, outcome=RoundOutcome.REFERRED, minute=1)
    await writer.resume(pursuit_id=pursuit_id, at=_EPOCH + timedelta(minutes=5))

    page = await lookup.list_pursuits(status=None, beamline=None, limit=_PAGE, cursor=None)

    (only,) = page.items
    assert only.status is PursuitStatus.RUNNING
    assert only.held_for is None


async def check_withdrawing_stops_the_pursuit_and_stamps_when(
    lookup: PursuitSummaryLookup, writer: PursuitWriter
) -> None:
    pursuit_id = await _one_pursuit(writer, minute=0)
    stopped = _EPOCH + timedelta(minutes=20)
    await writer.withdraw(pursuit_id=pursuit_id, at=stopped)

    page = await lookup.list_pursuits(status=None, beamline=None, limit=_PAGE, cursor=None)

    (only,) = page.items
    assert only.status is PursuitStatus.STOPPED
    assert only.stopped_at == stopped


async def check_withdrawing_a_held_pursuit_leaves_no_reason_behind(
    lookup: PursuitSummaryLookup, writer: PursuitWriter
) -> None:
    """A stopped pursuit is not waiting for anybody, and a reason left on
    the row would say a person is expected who is not."""
    pursuit_id = await _one_pursuit(writer, minute=0)
    await _a_round_ending(writer, pursuit_id, index=0, outcome=RoundOutcome.REFERRED, minute=1)
    await writer.withdraw(pursuit_id=pursuit_id, at=_EPOCH + timedelta(minutes=9))

    page = await lookup.list_pursuits(status=None, beamline=None, limit=_PAGE, cursor=None)

    (only,) = page.items
    assert only.status is PursuitStatus.STOPPED
    assert only.held_for is None


async def check_a_pursuit_walks_the_status_filter_forwards_and_back(
    lookup: PursuitSummaryLookup, writer: PursuitWriter
) -> None:
    """The check this whole contract exists for.

    Every read model before this one had a status that only went forwards,
    so a filter could be built out of "has this happened yet". A pursuit
    holds, resumes, holds again and is then withdrawn, and an adapter that
    assumed a lifecycle only moves one way passes every check above and
    fails here.
    """
    pursuit_id = await _one_pursuit(writer, minute=0)
    assert await _only(lookup, status=PursuitStatus.RUNNING) == [pursuit_id]

    await _a_round_ending(writer, pursuit_id, index=0, outcome=RoundOutcome.STALLED, minute=1)
    assert await _only(lookup, status=PursuitStatus.HELD) == [pursuit_id]
    assert await _only(lookup, status=PursuitStatus.RUNNING) == []

    await writer.resume(pursuit_id=pursuit_id, at=_EPOCH + timedelta(minutes=5))
    assert await _only(lookup, status=PursuitStatus.RUNNING) == [pursuit_id]
    assert await _only(lookup, status=PursuitStatus.HELD) == []

    await _a_round_ending(writer, pursuit_id, index=1, outcome=RoundOutcome.REFERRED, minute=8)
    assert await _only(lookup, status=PursuitStatus.HELD) == [pursuit_id]

    await writer.withdraw(pursuit_id=pursuit_id, at=_EPOCH + timedelta(minutes=12))
    assert await _only(lookup, status=PursuitStatus.STOPPED) == [pursuit_id]
    assert await _only(lookup, status=PursuitStatus.HELD) == []


async def check_the_beamline_filter_returns_only_that_beamlines_pursuits(
    lookup: PursuitSummaryLookup, writer: PursuitWriter
) -> None:
    here = await _one_pursuit(writer, minute=0, beamline="2-bm")
    await _one_pursuit(writer, minute=1, beamline="7-bm")

    assert await _only(lookup, beamline="2-bm") == [here]


async def check_the_two_filters_narrow_together(
    lookup: PursuitSummaryLookup, writer: PursuitWriter
) -> None:
    """The question somebody at a beamline actually asks: what may dispatch
    work here right now. Either filter alone answers something wider."""
    wanted = await _one_pursuit(writer, minute=0, beamline="2-bm")
    held_here = await _one_pursuit(writer, minute=1, beamline="2-bm")
    await _a_round_ending(writer, held_here, index=0, outcome=RoundOutcome.STALLED, minute=2)
    await _one_pursuit(writer, minute=3, beamline="7-bm")

    assert await _only(lookup, status=PursuitStatus.RUNNING, beamline="2-bm") == [wanted]


async def check_a_beamline_nothing_runs_at_returns_an_empty_page(
    lookup: PursuitSummaryLookup, writer: PursuitWriter
) -> None:
    await _one_pursuit(writer, minute=0, beamline="2-bm")

    assert await _only(lookup, beamline="11-id") == []


async def check_no_filter_returns_every_status(
    lookup: PursuitSummaryLookup, writer: PursuitWriter
) -> None:
    running = await _one_pursuit(writer, minute=0)
    held = await _one_pursuit(writer, minute=1)
    await _a_round_ending(writer, held, index=0, outcome=RoundOutcome.STALLED, minute=2)
    stopped = await _one_pursuit(writer, minute=3)
    await writer.withdraw(pursuit_id=stopped, at=_EPOCH + timedelta(minutes=4))

    assert set(await _only(lookup)) == {running, held, stopped}


async def check_pursuits_come_back_newest_first(
    lookup: PursuitSummaryLookup, writer: PursuitWriter
) -> None:
    first = await _one_pursuit(writer, minute=0)
    second = await _one_pursuit(writer, minute=1)
    third = await _one_pursuit(writer, minute=2)

    assert await _only(lookup) == [third, second, first]


async def check_a_full_page_hands_back_a_cursor_that_continues_it(
    lookup: PursuitSummaryLookup, writer: PursuitWriter
) -> None:
    newest = await _one_pursuit(writer, minute=2)
    middle = await _one_pursuit(writer, minute=1)
    oldest = await _one_pursuit(writer, minute=0)

    first = await lookup.list_pursuits(status=None, beamline=None, limit=2, cursor=None)
    assert [item.pursuit_id for item in first.items] == [newest, middle]
    assert first.next_cursor is not None

    second = await lookup.list_pursuits(
        status=None, beamline=None, limit=2, cursor=first.next_cursor
    )
    assert [item.pursuit_id for item in second.items] == [oldest]
    assert second.next_cursor is None


async def check_a_cursor_narrows_within_a_filter(
    lookup: PursuitSummaryLookup, writer: PursuitWriter
) -> None:
    """A page of held pursuits continues into held pursuits, not into
    whatever came next overall."""
    for minute in range(3):
        held = await _one_pursuit(writer, minute=minute)
        await _a_round_ending(writer, held, index=0, outcome=RoundOutcome.STALLED, minute=minute)
        await _one_pursuit(writer, minute=minute)

    first = await lookup.list_pursuits(
        status=PursuitStatus.HELD, beamline=None, limit=2, cursor=None
    )
    assert len(first.items) == 2
    assert first.next_cursor is not None

    second = await lookup.list_pursuits(
        status=PursuitStatus.HELD, beamline=None, limit=2, cursor=first.next_cursor
    )
    assert len(second.items) == 1
    assert all(item.status is PursuitStatus.HELD for item in second.items)


async def check_pursuits_started_at_one_instant_page_without_repeating_or_skipping(
    lookup: PursuitSummaryLookup, writer: PursuitWriter
) -> None:
    """The reason the id is in the sort key. Two pursuits at one instant
    have no order between them otherwise, and a page boundary inside the
    tie repeats a row or loses one."""
    expected = {await _one_pursuit(writer, minute=0) for _ in range(5)}

    seen: list[UUID] = []
    cursor: str | None = None
    while True:
        page = await lookup.list_pursuits(status=None, beamline=None, limit=2, cursor=cursor)
        seen.extend(item.pursuit_id for item in page.items)
        if page.next_cursor is None:
            break
        cursor = page.next_cursor

    assert len(seen) == len(set(seen)) == len(expected)
    assert set(seen) == expected


async def check_a_cursor_that_did_not_come_from_a_response_is_refused(
    lookup: PursuitSummaryLookup, writer: PursuitWriter
) -> None:
    _ = writer
    with pytest.raises(InvalidCursorError):
        await lookup.list_pursuits(status=None, beamline=None, limit=_PAGE, cursor="not-a-cursor")


async def check_a_cursor_past_the_end_returns_an_empty_page(
    lookup: PursuitSummaryLookup, writer: PursuitWriter
) -> None:
    await _one_pursuit(writer, minute=5)

    page = await lookup.list_pursuits(
        status=None,
        beamline=None,
        limit=_PAGE,
        cursor=encode_cursor(created_at=_EPOCH, item_id=UUID(int=0)),
    )

    assert page.items == []


CHECKS: tuple[Check, ...] = (
    check_an_empty_read_model_returns_an_empty_page,
    check_a_new_pursuit_shows_with_its_author_goal_and_beamline,
    check_a_new_pursuit_is_running_with_no_rounds_and_no_ending,
    check_opening_rounds_raises_the_count,
    check_an_advancing_round_leaves_the_pursuit_running,
    check_a_completing_round_stops_the_pursuit_without_an_ending_stamp,
    check_a_stalled_round_holds_the_pursuit_and_says_so,
    check_a_referred_round_holds_the_pursuit_and_says_so,
    check_resuming_clears_the_hold_and_its_reason,
    check_withdrawing_stops_the_pursuit_and_stamps_when,
    check_withdrawing_a_held_pursuit_leaves_no_reason_behind,
    check_a_pursuit_walks_the_status_filter_forwards_and_back,
    check_the_beamline_filter_returns_only_that_beamlines_pursuits,
    check_the_two_filters_narrow_together,
    check_a_beamline_nothing_runs_at_returns_an_empty_page,
    check_no_filter_returns_every_status,
    check_pursuits_come_back_newest_first,
    check_a_full_page_hands_back_a_cursor_that_continues_it,
    check_a_cursor_narrows_within_a_filter,
    check_pursuits_started_at_one_instant_page_without_repeating_or_skipping,
    check_a_cursor_that_did_not_come_from_a_response_is_refused,
    check_a_cursor_past_the_end_returns_an_empty_page,
)
"""Every behaviour, in the order a reader should meet them.

A tuple rather than a module scan, so adding a check means adding it here
and a check written and never listed fails nothing quietly.
"""

__all__ = ["CHECKS", "Check", "PursuitWriter"]
