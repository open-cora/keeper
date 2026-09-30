"""Behaviour every `StepSummaryLookup` adapter owes its callers.

The fifth summary contract and the one with the most to prove, because
the two adapters do not merely reach one answer differently: they reach
it from different halves of different bounded contexts.

One reads a projection table where a worker has already folded
execution events and dataset events into one row per step, and asks it
for the rows with a reference and no dataset. The other holds no table
at all. It folds every execution stream for the steps that named a run,
reads every dataset stream for the steps something holds, and subtracts
the second from the first.

Nothing about those two resembles the other, and the question they
answer is a negative one, which is the kind that fails quietly. An
adapter that could not see datasets would report every run in the
facility as a gap and look busy rather than broken, and an adapter that
could not see executions would report nothing and look like a facility
with no gaps. Both are what this compares.
"""

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID, uuid4

import pytest

from keeper.execution.aggregates.execution.state import ExecutionBeamline
from keeper.execution.aggregates.execution.step_summary import StepSummaryLookup
from keeper.infrastructure.projection.cursor import InvalidCursorError, encode_cursor
from keeper.shared.identifier import Identifier


class StepWriter(Protocol):
    """Put executions, steps and datasets where the adapter will find them."""

    async def dispatch(
        self,
        *,
        execution_id: UUID,
        procedure_id: UUID,
        steps: list[str],
        at: datetime,
        beamline: str = "2-bm",
        step_ids: list[UUID] | None = None,
    ) -> None:
        """Write an execution down, with step ids the caller can name later."""
        ...

    async def step(
        self,
        *,
        execution_id: UUID,
        index: int,
        at: datetime,
        engine_reference: str | None = None,
    ) -> None:
        """Report one step done, naming the run it opened when it opened one."""
        ...

    async def register(
        self,
        *,
        dataset_id: UUID,
        execution_id: UUID,
        step_id: UUID,
        external_ref: Identifier,
        at: datetime,
    ) -> None:
        """Say where one step's output is being kept."""
        ...


Check = Callable[[StepSummaryLookup, StepWriter], Awaitable[None]]
"""One behaviour, applied to whichever adapter the driver supplies."""

_EPOCH = datetime(2026, 3, 1, 9, 0, tzinfo=UTC)
"""A fixed instant the checks below count minutes from.

Fixed rather than `now`, so an ordering assertion reads as an ordering
rather than as arithmetic on the wall clock.
"""

_PAGE = 50
"""A limit wide enough that paging does not interfere with other checks."""

_SET = "set 2bmb:m1 to 0.0"
_RUN = "run tomo_scan"


async def _an_execution(
    writer: StepWriter,
    *,
    minute: int,
    references: list[str | None],
    beamline: str = "2-bm",
) -> tuple[UUID, list[UUID]]:
    """One execution whose steps report in order, and its step ids.

    `references` is one entry per step: a string for a step that opened
    a run the engine named, None for one that opened none. That is the
    only axis these checks vary, because it is the only one the
    question turns on.
    """
    execution_id, step_ids = uuid4(), [uuid4() for _ in references]
    await writer.dispatch(
        execution_id=execution_id,
        procedure_id=uuid4(),
        steps=[_RUN if reference else _SET for reference in references],
        at=_EPOCH + timedelta(minutes=minute),
        beamline=beamline,
        step_ids=step_ids,
    )
    for index, reference in enumerate(references):
        await writer.step(
            execution_id=execution_id,
            index=index,
            at=_EPOCH + timedelta(minutes=minute, seconds=index + 1),
            engine_reference=reference,
        )
    return execution_id, step_ids


async def _file(
    writer: StepWriter, *, execution_id: UUID, step_id: UUID, minute: int, value: str
) -> None:
    await writer.register(
        dataset_id=uuid4(),
        execution_id=execution_id,
        step_id=step_id,
        external_ref=Identifier(scheme="posix-file", value=value),
        at=_EPOCH + timedelta(minutes=minute),
    )


async def _listed(
    lookup: StepSummaryLookup, *, beamline: str | None = None, limit: int = _PAGE
) -> list[UUID]:
    page = await lookup.list_steps_without_datasets(
        beamline=ExecutionBeamline(beamline) if beamline is not None else None,
        limit=limit,
        cursor=None,
    )
    return [item.step_id for item in page.items]


async def check_an_empty_read_model_returns_an_empty_page(
    lookup: StepSummaryLookup, writer: StepWriter
) -> None:
    _ = writer
    page = await lookup.list_steps_without_datasets(beamline=None, limit=_PAGE, cursor=None)

    assert page.items == []
    assert page.next_cursor is None


async def check_a_run_nothing_filed_comes_back_with_what_it_produced(
    lookup: StepSummaryLookup, writer: StepWriter
) -> None:
    """The whole question, in one execution of one step."""
    execution_id, (step_id,) = await _an_execution(
        writer, minute=1, references=["/data/2bm/tomo_0001.h5"]
    )

    page = await lookup.list_steps_without_datasets(beamline=None, limit=_PAGE, cursor=None)

    (only,) = page.items
    assert (only.step_id, only.execution_id) == (step_id, execution_id)
    assert only.engine_reference == "/data/2bm/tomo_0001.h5"
    assert only.describes == _RUN
    assert only.beamline == ExecutionBeamline("2-bm")
    assert only.index == 0
    assert only.outcome == "Done"
    assert only.reported_at is not None


async def check_a_run_whose_data_was_filed_is_gone_from_the_listing(
    lookup: StepSummaryLookup, writer: StepWriter
) -> None:
    """The half that fails silently if an adapter cannot see datasets."""
    execution_id, (step_id,) = await _an_execution(writer, minute=1, references=["/data/a.h5"])
    assert await _listed(lookup) == [step_id]

    await _file(writer, execution_id=execution_id, step_id=step_id, minute=2, value="/data/a.h5")

    assert await _listed(lookup) == []


async def check_a_step_that_opened_no_run_is_never_a_gap(
    lookup: StepSummaryLookup, writer: StepWriter
) -> None:
    """A move produced nothing, so it is not missing anything.

    The check that stops this listing from growing with the size of
    every procedure rather than with the number of runs.
    """
    await _an_execution(writer, minute=1, references=[None, None, None])

    assert await _listed(lookup) == []


async def check_only_the_unfiled_runs_of_a_mixed_execution_come_back(
    lookup: StepSummaryLookup, writer: StepWriter
) -> None:
    """One execution holding all three kinds at once."""
    execution_id, step_ids = await _an_execution(
        writer, minute=1, references=[None, "/data/b.h5", "/data/c.h5"]
    )
    await _file(
        writer, execution_id=execution_id, step_id=step_ids[1], minute=2, value="/data/b.h5"
    )

    assert await _listed(lookup) == [step_ids[2]]


async def check_a_beamline_filter_returns_only_that_stations_gaps(
    lookup: StepSummaryLookup, writer: StepWriter
) -> None:
    _, (here,) = await _an_execution(
        writer, minute=1, references=["/data/here.h5"], beamline="2-bm"
    )
    await _an_execution(writer, minute=2, references=["/data/there.h5"], beamline="32-id")

    assert await _listed(lookup, beamline="2-bm") == [here]


async def check_a_beamline_with_no_gaps_returns_an_empty_page(
    lookup: StepSummaryLookup, writer: StepWriter
) -> None:
    await _an_execution(writer, minute=1, references=["/data/there.h5"], beamline="32-id")

    assert await _listed(lookup, beamline="2-bm") == []


async def check_gaps_come_back_newest_first(lookup: StepSummaryLookup, writer: StepWriter) -> None:
    """Newest first, because what went unrecorded lately is what is wrong now."""
    _, (older,) = await _an_execution(writer, minute=1, references=["/data/older.h5"])
    _, (newer,) = await _an_execution(writer, minute=5, references=["/data/newer.h5"])

    assert await _listed(lookup) == [newer, older]


async def check_a_full_page_hands_back_a_cursor_that_continues_it(
    lookup: StepSummaryLookup, writer: StepWriter
) -> None:
    _, (older,) = await _an_execution(writer, minute=1, references=["/data/older.h5"])
    _, (newer,) = await _an_execution(writer, minute=5, references=["/data/newer.h5"])

    first = await lookup.list_steps_without_datasets(beamline=None, limit=1, cursor=None)
    assert [item.step_id for item in first.items] == [newer]
    assert first.next_cursor is not None

    second = await lookup.list_steps_without_datasets(
        beamline=None, limit=1, cursor=first.next_cursor
    )
    assert [item.step_id for item in second.items] == [older]


async def check_the_last_page_hands_back_no_cursor(
    lookup: StepSummaryLookup, writer: StepWriter
) -> None:
    await _an_execution(writer, minute=1, references=["/data/only.h5"])

    page = await lookup.list_steps_without_datasets(beamline=None, limit=_PAGE, cursor=None)

    assert len(page.items) == 1
    assert page.next_cursor is None


async def check_a_cursor_narrows_within_a_filter(
    lookup: StepSummaryLookup, writer: StepWriter
) -> None:
    """Paging a filtered listing must not walk out of the filter."""
    _, (older,) = await _an_execution(
        writer, minute=1, references=["/data/older.h5"], beamline="2-bm"
    )
    await _an_execution(writer, minute=3, references=["/data/other.h5"], beamline="32-id")
    _, (newer,) = await _an_execution(
        writer, minute=5, references=["/data/newer.h5"], beamline="2-bm"
    )

    here = ExecutionBeamline("2-bm")
    first = await lookup.list_steps_without_datasets(beamline=here, limit=1, cursor=None)
    assert [item.step_id for item in first.items] == [newer]

    second = await lookup.list_steps_without_datasets(
        beamline=here, limit=1, cursor=first.next_cursor
    )
    assert [item.step_id for item in second.items] == [older]


async def check_gaps_reported_at_one_instant_page_without_repeating_or_skipping(
    lookup: StepSummaryLookup, writer: StepWriter
) -> None:
    """The tie the step id is in the sort key to break.

    Three runs reported in the same instant, read one page at a time.
    An ordering that broke ties differently per page would show one of
    them twice and lose another, and the totals are what catch it.
    """
    for _ in range(3):
        await _an_execution(writer, minute=1, references=["/data/same-instant.h5"])

    seen: list[UUID] = []
    cursor: str | None = None
    for _ in range(3):
        page = await lookup.list_steps_without_datasets(beamline=None, limit=1, cursor=cursor)
        seen.extend(item.step_id for item in page.items)
        cursor = page.next_cursor

    assert len(seen) == 3
    assert len(set(seen)) == 3


async def check_a_cursor_that_did_not_come_from_a_response_is_refused(
    lookup: StepSummaryLookup, writer: StepWriter
) -> None:
    _ = writer
    with pytest.raises(InvalidCursorError):
        await lookup.list_steps_without_datasets(beamline=None, limit=_PAGE, cursor="not-a-cursor")


async def check_a_cursor_past_the_end_returns_an_empty_page(
    lookup: StepSummaryLookup, writer: StepWriter
) -> None:
    await _an_execution(writer, minute=5, references=["/data/only.h5"])

    page = await lookup.list_steps_without_datasets(
        beamline=None,
        limit=_PAGE,
        cursor=encode_cursor(created_at=_EPOCH, item_id=uuid4()),
    )

    assert page.items == []
    assert page.next_cursor is None


CHECKS: tuple[Check, ...] = (
    check_an_empty_read_model_returns_an_empty_page,
    check_a_run_nothing_filed_comes_back_with_what_it_produced,
    check_a_run_whose_data_was_filed_is_gone_from_the_listing,
    check_a_step_that_opened_no_run_is_never_a_gap,
    check_only_the_unfiled_runs_of_a_mixed_execution_come_back,
    check_a_beamline_filter_returns_only_that_stations_gaps,
    check_a_beamline_with_no_gaps_returns_an_empty_page,
    check_gaps_come_back_newest_first,
    check_a_full_page_hands_back_a_cursor_that_continues_it,
    check_the_last_page_hands_back_no_cursor,
    check_a_cursor_narrows_within_a_filter,
    check_gaps_reported_at_one_instant_page_without_repeating_or_skipping,
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


__all__ = ["CHECKS", "Check", "StepWriter", "checks_defined_but_not_listed"]
