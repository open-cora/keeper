"""Behaviour every `DatasetSummaryLookup` adapter owes its callers.

The third summary contract, and the same reason for existing as the two
beside it: one side reads a table a worker maintains, the other folds
every stream, and nothing about the code on one resembles the other.

What differs here is the filter. A plan name is not unique and a step's
external reference is meant to be; a step id is neither, it is a real
one-to-many. How many datasets a step produces is the reporting side's
policy rather than a rule in the model, so the several-matches case is
not an edge to tolerate but the shape the slice is for.

The other difference is smaller and worth saying: a dataset has one
event, so there is no transition to check and no second timestamp to
watch move.
"""

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID, uuid4

import pytest

from keeper.custody.aggregates.dataset.summary import DatasetSummaryLookup
from keeper.infrastructure.projection.cursor import InvalidCursorError, encode_cursor
from keeper.shared.identifier import Identifier


class DatasetWriter(Protocol):
    """Put datasets where the adapter under test will find them."""

    async def register(
        self,
        *,
        dataset_id: UUID,
        execution_id: UUID,
        step_id: UUID,
        external_ref: Identifier,
        at: datetime,
    ) -> None:
        """Write a dataset down."""
        ...


Check = Callable[[DatasetSummaryLookup, DatasetWriter], Awaitable[None]]
"""One behaviour, applied to whichever adapter the driver supplies."""

_EPOCH = datetime(2026, 3, 1, 9, 0, tzinfo=UTC)
"""A fixed instant the checks below count minutes from.

Fixed rather than `now`, so an ordering assertion reads as an ordering
rather than as arithmetic on the wall clock.
"""

_PAGE = 50
"""A limit wide enough that paging does not interfere with other checks."""


async def _one_dataset(
    writer: DatasetWriter,
    *,
    step_id: UUID,
    minute: int,
    value: str | None = None,
    execution_id: UUID | None = None,
) -> UUID:
    dataset_id = uuid4()
    await writer.register(
        dataset_id=dataset_id,
        execution_id=execution_id if execution_id is not None else uuid4(),
        step_id=step_id,
        external_ref=Identifier(
            scheme="example-store-path",
            value=value or f"raw/{dataset_id}",
        ),
        at=_EPOCH + timedelta(minutes=minute),
    )
    return dataset_id


async def check_an_empty_read_model_returns_an_empty_page(
    lookup: DatasetSummaryLookup, writer: DatasetWriter
) -> None:
    _ = writer
    page = await lookup.list_datasets(step_id=None, limit=_PAGE, cursor=None)
    assert page.items == []
    assert page.next_cursor is None


async def check_a_registered_dataset_shows_with_its_step_reference_and_time(
    lookup: DatasetSummaryLookup, writer: DatasetWriter
) -> None:
    step_id = uuid4()
    dataset_id = await _one_dataset(writer, step_id=step_id, minute=0, value="raw/one")

    page = await lookup.list_datasets(step_id=None, limit=_PAGE, cursor=None)

    (summary,) = page.items
    assert summary.dataset_id == dataset_id
    assert summary.step_id == step_id
    assert summary.external_ref == Identifier(scheme="example-store-path", value="raw/one")
    assert summary.created_at == _EPOCH


async def check_a_step_filter_returns_only_what_that_acquisition_produced(
    lookup: DatasetSummaryLookup, writer: DatasetWriter
) -> None:
    wanted_step = uuid4()
    await _one_dataset(writer, step_id=uuid4(), minute=0)
    wanted = await _one_dataset(writer, step_id=wanted_step, minute=1)

    page = await lookup.list_datasets(step_id=wanted_step, limit=_PAGE, cursor=None)

    assert [summary.dataset_id for summary in page.items] == [wanted]


async def check_a_step_that_produced_nothing_returns_an_empty_page(
    lookup: DatasetSummaryLookup, writer: DatasetWriter
) -> None:
    """The honest answer for a step whose data never landed, and the one a
    caller most needs to tell apart from an error."""
    await _one_dataset(writer, step_id=uuid4(), minute=0)

    page = await lookup.list_datasets(step_id=uuid4(), limit=_PAGE, cursor=None)

    assert page.items == []
    assert page.next_cursor is None


async def check_every_dataset_one_acquisition_produced_comes_back(
    lookup: DatasetSummaryLookup, writer: DatasetWriter
) -> None:
    """The shape this slice is for. One dataset per step is the reporting
    side's policy and not a rule here, so a lookup returning one of
    several would be enforcing in the read model what the write model
    deliberately declined to enforce."""
    step_id = uuid4()
    first = await _one_dataset(writer, step_id=step_id, minute=0)
    second = await _one_dataset(writer, step_id=step_id, minute=1)
    third = await _one_dataset(writer, step_id=step_id, minute=2)

    page = await lookup.list_datasets(step_id=step_id, limit=_PAGE, cursor=None)

    assert {summary.dataset_id for summary in page.items} == {first, second, third}


async def check_two_datasets_naming_one_address_both_come_back(
    lookup: DatasetSummaryLookup, writer: DatasetWriter
) -> None:
    """A duplicate is shown rather than swallowed. There is no unique
    index on the reference, because enforcing one here would drop a row
    that exists in the log and leave it missing from every listing."""
    step_id = uuid4()
    first = await _one_dataset(writer, step_id=step_id, minute=0, value="raw/same")
    second = await _one_dataset(writer, step_id=step_id, minute=1, value="raw/same")

    page = await lookup.list_datasets(step_id=step_id, limit=_PAGE, cursor=None)

    assert {summary.dataset_id for summary in page.items} == {first, second}


async def check_datasets_come_back_newest_first(
    lookup: DatasetSummaryLookup, writer: DatasetWriter
) -> None:
    step_id = uuid4()
    oldest = await _one_dataset(writer, step_id=step_id, minute=0)
    middle = await _one_dataset(writer, step_id=step_id, minute=1)
    newest = await _one_dataset(writer, step_id=step_id, minute=2)

    page = await lookup.list_datasets(step_id=None, limit=_PAGE, cursor=None)

    assert [summary.dataset_id for summary in page.items] == [newest, middle, oldest]


async def check_a_full_page_hands_back_a_cursor_that_continues_it(
    lookup: DatasetSummaryLookup, writer: DatasetWriter
) -> None:
    """Every dataset exactly once across the pages, in one order. A
    boundary that repeated a row or dropped one would still satisfy a
    check that only counted them."""
    step_id = uuid4()
    ids = [await _one_dataset(writer, step_id=step_id, minute=i) for i in range(5)]

    first = await lookup.list_datasets(step_id=None, limit=2, cursor=None)
    second = await lookup.list_datasets(step_id=None, limit=2, cursor=first.next_cursor)
    third = await lookup.list_datasets(step_id=None, limit=2, cursor=second.next_cursor)

    assert third.next_cursor is None
    walked = [summary.dataset_id for page in (first, second, third) for summary in page.items]
    assert walked == list(reversed(ids))


async def check_the_last_page_hands_back_no_cursor(
    lookup: DatasetSummaryLookup, writer: DatasetWriter
) -> None:
    """A page exactly as long as the limit is still the last page when
    nothing follows it."""
    step_id = uuid4()
    await _one_dataset(writer, step_id=step_id, minute=0)
    await _one_dataset(writer, step_id=step_id, minute=1)

    page = await lookup.list_datasets(step_id=None, limit=2, cursor=None)

    assert len(page.items) == 2
    assert page.next_cursor is None


async def check_a_cursor_narrows_within_a_filter(
    lookup: DatasetSummaryLookup, writer: DatasetWriter
) -> None:
    """Paging and filtering compose, which matters here for the same
    reason it does on the plan side: several rows under one filter value
    is the ordinary case, so the second page has to stay under it."""
    wanted_step = uuid4()
    await _one_dataset(writer, step_id=uuid4(), minute=0)
    wanted = [await _one_dataset(writer, step_id=wanted_step, minute=i) for i in (1, 2, 3)]

    first = await lookup.list_datasets(step_id=wanted_step, limit=2, cursor=None)
    second = await lookup.list_datasets(step_id=wanted_step, limit=2, cursor=first.next_cursor)

    walked = [summary.dataset_id for page in (first, second) for summary in page.items]
    assert walked == list(reversed(wanted))


async def check_datasets_written_at_one_instant_page_without_repeating_or_skipping(
    lookup: DatasetSummaryLookup, writer: DatasetWriter
) -> None:
    """The tie the id in the sort key exists for, and it is the ordinary
    case here rather than the backfill case: a step producing several
    datasets at once stamps them all with one instant. Ordered by time
    alone, a page boundary inside the tie repeats a row or drops one."""
    step_id = uuid4()
    ids = {await _one_dataset(writer, step_id=step_id, minute=0) for _ in range(4)}

    first = await lookup.list_datasets(step_id=step_id, limit=2, cursor=None)
    second = await lookup.list_datasets(step_id=step_id, limit=2, cursor=first.next_cursor)

    walked = [summary.dataset_id for page in (first, second) for summary in page.items]
    assert len(walked) == 4
    assert set(walked) == ids


async def check_a_cursor_that_did_not_come_from_a_response_is_refused(
    lookup: DatasetSummaryLookup, writer: DatasetWriter
) -> None:
    _ = writer
    with pytest.raises(InvalidCursorError):
        await lookup.list_datasets(step_id=None, limit=_PAGE, cursor="not-a-cursor")


async def check_a_cursor_past_the_end_returns_an_empty_page(
    lookup: DatasetSummaryLookup, writer: DatasetWriter
) -> None:
    await _one_dataset(writer, step_id=uuid4(), minute=10)

    page = await lookup.list_datasets(
        step_id=None,
        limit=_PAGE,
        cursor=encode_cursor(created_at=_EPOCH, item_id=uuid4()),
    )

    assert page.items == []
    assert page.next_cursor is None


CHECKS: tuple[Check, ...] = (
    check_an_empty_read_model_returns_an_empty_page,
    check_a_registered_dataset_shows_with_its_step_reference_and_time,
    check_a_step_filter_returns_only_what_that_acquisition_produced,
    check_a_step_that_produced_nothing_returns_an_empty_page,
    check_every_dataset_one_acquisition_produced_comes_back,
    check_two_datasets_naming_one_address_both_come_back,
    check_datasets_come_back_newest_first,
    check_a_full_page_hands_back_a_cursor_that_continues_it,
    check_the_last_page_hands_back_no_cursor,
    check_a_cursor_narrows_within_a_filter,
    check_datasets_written_at_one_instant_page_without_repeating_or_skipping,
    check_a_cursor_that_did_not_come_from_a_response_is_refused,
    check_a_cursor_past_the_end_returns_an_empty_page,
)
"""Every check above. Hand-written; the drivers guard against omissions."""


def checks_defined_but_not_listed() -> frozenset[str]:
    """Check functions defined in this module that `CHECKS` leaves out.

    The tuple is the contract; a function absent from it steps nowhere.
    """
    listed = {check.__name__ for check in CHECKS}
    defined = {
        name for name, value in globals().items() if name.startswith("check_") and callable(value)
    }
    return frozenset(defined - listed)


__all__ = ["CHECKS", "Check", "DatasetWriter", "checks_defined_but_not_listed"]
