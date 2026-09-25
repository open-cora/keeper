"""Answer the same question by folding, when there is no table to read.

The in-memory half of the `DatasetSummaryLookup` port. It exists because
this application is meant to boot and answer with no database at all,
which is what the unit and contract tiers run against. In that
environment no projection worker runs, so the table the other adapter
reads does not exist and never fills.

So this one recomputes. Every dataset stream, folded, filtered, sorted,
paged. That is precisely the cost a projection exists to avoid, and it is
the right trade here: the store is a dictionary, the streams number in
the tens, and the alternative is a surface that works in production and
refuses in every test.

## Why the two halves can be trusted to agree

They cannot, on inspection. `tests/_port_contracts/dataset_summary_lookup.py`
is one suite run against both, which is the only thing that makes the
claim checkable, and `test_port_contracts_have_two_sides.py` fails if the
second driver ever goes away.

The one thing this cannot reproduce is lag. A projection is eventually
consistent and this is immediate, so a test that passes here says nothing
about a caller reading too soon. That is the integration tier's job, and
`drain_projections` is how it asks the question without sleeping.
"""

from uuid import UUID

from keeper.custody.aggregates.dataset.events import from_stored
from keeper.custody.aggregates.dataset.evolver import fold
from keeper.custody.aggregates.dataset.read import DATASET_STREAM_TYPE
from keeper.custody.aggregates.dataset.summary import DatasetSummary, DatasetSummaryPage
from keeper.infrastructure.adapters.in_memory_event_store import InMemoryEventStore
from keeper.infrastructure.projection.cursor import decode_cursor, encode_cursor


class InMemoryDatasetSummaryLookup:
    """Fold-everything implementation of the `DatasetSummaryLookup` port.

    Typed against the concrete in-memory store rather than the
    `EventStore` port, because enumerating streams is not something the
    port offers and should not become something it offers. An adapter for
    the in-memory environment depending on the in-memory store is honest
    about what it is.
    """

    def __init__(self, event_store: InMemoryEventStore) -> None:
        self._event_store = event_store

    async def list_datasets(
        self,
        *,
        step_id: UUID | None,
        limit: int,
        cursor: str | None,
    ) -> DatasetSummaryPage:
        """Return one page of datasets, newest first."""
        summaries = [
            summary
            for summary in await self._all_summaries()
            if step_id is None or summary.step_id == step_id
        ]
        summaries.sort(key=lambda summary: (summary.created_at, summary.dataset_id), reverse=True)

        after = decode_cursor(cursor) if cursor is not None else None
        if after is not None:
            summaries = [
                summary for summary in summaries if (summary.created_at, summary.dataset_id) < after
            ]

        page, has_more = summaries[:limit], len(summaries) > limit
        next_cursor = (
            encode_cursor(created_at=page[-1].created_at, item_id=page[-1].dataset_id)
            if has_more and page
            else None
        )
        return DatasetSummaryPage(items=page, next_cursor=next_cursor)

    async def _all_summaries(self) -> list[DatasetSummary]:
        """Fold every dataset stream into the row a projection would write.

        The timestamp comes off the envelope of the first event, which is
        the same value the projection's INSERT writes. The rest comes from
        the fold, so the reference here is the evolver's own answer rather
        than a second reading of the payload that could disagree with it.
        """
        summaries: list[DatasetSummary] = []
        for dataset_id in self._event_store.stream_ids(DATASET_STREAM_TYPE):
            stored, _version = await self._event_store.load(DATASET_STREAM_TYPE, dataset_id)
            dataset = fold([from_stored(row) for row in stored])
            if dataset is None:
                continue
            summaries.append(
                DatasetSummary(
                    dataset_id=dataset.id,
                    execution_id=dataset.execution_id,
                    step_id=dataset.step_id,
                    external_ref=dataset.external_ref,
                    created_at=stored[0].occurred_at,
                )
            )
        return summaries


__all__ = ["InMemoryDatasetSummaryLookup"]
