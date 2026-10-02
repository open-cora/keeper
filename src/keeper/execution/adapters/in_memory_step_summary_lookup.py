"""Answer the same question by folding, when there is no table to read.

The in-memory half of the `StepSummaryLookup` port. It exists because
this application is meant to boot and answer with no database at all,
which is what the unit and contract tiers run against. In that
environment no projection worker runs, so the table the other adapter
reads does not exist and never fills.

So this one recomputes: every execution stream folded for its steps,
every dataset stream read for the steps it names, and the difference
returned. That is precisely the cost a projection exists to avoid, and
it is the right trade here for the reason every sibling adapter gives.

## Why Custody is named with strings

This reads dataset streams and imports nothing from Custody. It cannot:
Custody already reaches into Execution to check that a step exists
before it registers a dataset against one, so an import the other way
would close a cycle and `tach` would refuse it.

Naming the producer with a string is the sanctioned way across that
line and is what the projection does with the event type. The two
literals here are pinned against Custody's own constants by
`tests/unit/test_step_summary_names_custody_correctly.py`, because a
string nothing compares is a rename waiting to make this adapter
quietly answer that every run is unfiled.
"""

from datetime import datetime
from typing import Final
from uuid import UUID

from keeper.execution.aggregates.execution.events import from_stored
from keeper.execution.aggregates.execution.evolver import fold
from keeper.execution.aggregates.execution.read import EXECUTION_STREAM_TYPE
from keeper.execution.aggregates.execution.state import ExecutionBeamline, StepOutcome
from keeper.execution.aggregates.execution.step_summary import StepSummary, StepSummaryPage
from keeper.infrastructure.adapters.in_memory_event_store import InMemoryEventStore
from keeper.infrastructure.projection.cursor import decode_cursor, encode_cursor

DATASET_STREAM_TYPE: Final = "Dataset"
"""What Custody calls its streams, spelled here rather than imported."""

DATASET_REGISTERED_EVENT_TYPE: Final = "DatasetRegistered"
"""The event that says a step's output is being held somewhere."""

_STEP_OUTCOME_EVENT_TYPES: Final[frozenset[str]] = frozenset(
    {
        "ExecutionStepDone",
        "ExecutionStepRefused",
        "ExecutionStepBroken",
        "ExecutionStepSkipped",
    }
)
"""The events that carry the moment a step was reported.

The fold keeps a step's outcome and not when it landed, because nothing
in the domain asks. This read model does ask, so the times are taken
off the stored envelopes rather than added to the state for one caller.
"""


class InMemoryStepSummaryLookup:
    """Fold-everything implementation of the `StepSummaryLookup` port.

    Typed against the concrete in-memory store rather than the
    `EventStore` port, because enumerating streams is not something the
    port offers and should not become something it offers.
    """

    def __init__(self, event_store: InMemoryEventStore) -> None:
        self._event_store = event_store

    async def list_steps_without_datasets(
        self,
        *,
        beamline: ExecutionBeamline | None,
        limit: int,
        cursor: str | None,
    ) -> StepSummaryPage:
        """Return one page of runs whose output nothing recorded."""
        held = await self._steps_with_a_dataset()
        summaries = [
            summary
            for summary in await self._runs_reported()
            if summary.step_id not in held and (beamline is None or summary.beamline == beamline)
        ]
        summaries.sort(key=_sort_key, reverse=True)

        after = decode_cursor(cursor) if cursor is not None else None
        if after is not None:
            summaries = [summary for summary in summaries if _sort_key(summary) < after]

        page, has_more = summaries[:limit], len(summaries) > limit
        next_cursor = (
            encode_cursor(created_at=_sort_key(page[-1])[0], item_id=page[-1].step_id)
            if has_more and page
            else None
        )
        return StepSummaryPage(items=page, next_cursor=next_cursor)

    async def _steps_with_a_dataset(self) -> set[UUID]:
        """Every step some dataset names, however many name one step."""
        held: set[UUID] = set()
        for dataset_id in self._event_store.stream_ids(DATASET_STREAM_TYPE):
            stored, _version = await self._event_store.load(DATASET_STREAM_TYPE, dataset_id)
            held.update(
                UUID(str(row.payload["step_id"]))
                for row in stored
                if row.event_type == DATASET_REGISTERED_EVENT_TYPE
            )
        return held

    async def _runs_reported(self) -> list[StepSummary]:
        """Fold every execution stream into the steps that named a run.

        Not every step, which is what the sibling adapter's equivalent
        returns and what the table holds. The table cannot know at
        dispatch which steps will open a run, so it keeps a row for
        each; here the fold has already happened and the answer is on
        the step.

        That makes this the only place the run filter is applied, which
        is deliberate. It was in both this and the caller, and a filter
        stated twice is one that can be deleted from either place
        without a test noticing.

        The filter is the engine state rather than the reference, which
        is the fold's way of spelling the sibling's `run_opened_at`: a
        step whose engine state is set is a step something watched a run
        open on. The reference cannot stand in for it, because an engine
        that publishes no identifier opens runs this would then drop.

        Being reported is required too, and for the sibling's reason. A
        run reaches this list when it begins, so without that a scan
        still running reads as a run whose data nobody recorded.
        """
        summaries: list[StepSummary] = []
        for execution_id in self._event_store.stream_ids(EXECUTION_STREAM_TYPE):
            stored, _version = await self._event_store.load(EXECUTION_STREAM_TYPE, execution_id)
            execution = fold([from_stored(row) for row in stored])
            if execution is None:
                continue
            reported = {
                int(row.payload["index"]): row.occurred_at
                for row in stored
                if row.event_type in _STEP_OUTCOME_EVENT_TYPES
            }
            summaries.extend(
                StepSummary(
                    step_id=step.id,
                    execution_id=execution.id,
                    index=index,
                    describes=step.describes,
                    beamline=execution.beamline,
                    outcome=_named(step.outcome),
                    engine_reference=step.engine_reference,
                    reported_at=reported.get(index),
                    dataset_id=None,
                    filed_at=None,
                )
                for index, step in enumerate(execution.steps)
                if step.engine_state is not None and reported.get(index) is not None
            )
        return summaries


def _named(outcome: StepOutcome | None) -> str | None:
    """The outcome as the table spells it, which is its own value."""
    return None if outcome is None else outcome.value


def _sort_key(summary: StepSummary) -> tuple[datetime, UUID]:
    """The pair the table sorts and pages on.

    `reported_at` is never None for a row this adapter returns, because
    a step carrying an engine reference reported an outcome to carry it
    on. The assertion says so rather than a `cast`, so a fold that ever
    produced one would fail here instead of sorting into an arbitrary
    place and paging past rows a caller needed.
    """
    assert summary.reported_at is not None, (
        f"step {summary.step_id} names a run and has no report behind it"
    )
    return (summary.reported_at, summary.step_id)


__all__ = [
    "DATASET_REGISTERED_EVENT_TYPE",
    "DATASET_STREAM_TYPE",
    "InMemoryStepSummaryLookup",
]
