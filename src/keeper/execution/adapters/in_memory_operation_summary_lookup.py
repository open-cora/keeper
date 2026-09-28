"""Answer the same questions by folding, when there is no table to read.

The in-memory half of the `OperationSummaryLookup` port, and the run lookup's
sibling. Same reason for existing: this application boots and answers with
no database, which is what the unit and contract tiers run against, and in
that environment no projection worker runs so the table the other adapter
reads never fills.

Same trade too. Every operation stream, folded, sorted, filtered, paged, which
is the cost a projection exists to avoid and is free when the store is a
dictionary. `tests/_port_contracts/operation_summary_lookup.py` is what makes
"the two answer alike" a checkable claim rather than a hopeful one.
"""

from keeper.execution.aggregates.operation.events import from_stored
from keeper.execution.aggregates.operation.evolver import fold
from keeper.execution.aggregates.operation.read import OPERATION_STREAM_TYPE
from keeper.execution.aggregates.operation.state import OperationName
from keeper.execution.aggregates.operation.summary import OperationSummary, OperationSummaryPage
from keeper.infrastructure.adapters.in_memory_event_store import InMemoryEventStore
from keeper.infrastructure.projection.cursor import decode_cursor, encode_cursor


class InMemoryOperationSummaryLookup:
    """Fold-everything implementation of the `OperationSummaryLookup` port.

    Typed against the concrete in-memory store rather than the
    `EventStore` port, because enumerating streams is not something the
    port offers and should not become something it offers.
    """

    def __init__(self, event_store: InMemoryEventStore) -> None:
        self._event_store = event_store

    async def list_operations(
        self,
        *,
        name: OperationName | None,
        limit: int,
        cursor: str | None,
    ) -> OperationSummaryPage:
        """Return one page of operations, newest first."""
        summaries = [
            summary
            for summary in await self._all_summaries()
            if name is None or summary.name == name
        ]
        summaries.sort(key=lambda summary: (summary.created_at, summary.operation_id), reverse=True)

        after = decode_cursor(cursor) if cursor is not None else None
        if after is not None:
            summaries = [
                summary
                for summary in summaries
                if (summary.created_at, summary.operation_id) < after
            ]

        page, has_more = summaries[:limit], len(summaries) > limit
        next_cursor = (
            encode_cursor(created_at=page[-1].created_at, item_id=page[-1].operation_id)
            if has_more and page
            else None
        )
        return OperationSummaryPage(items=page, next_cursor=next_cursor)

    async def _all_summaries(self) -> list[OperationSummary]:
        """Fold every operation stream into the row a projection would write.

        `created_at` comes off the envelope, which for an operation is the only
        event there is, so there is no first-and-last pair to keep
        straight the way the run side has.
        """
        summaries: list[OperationSummary] = []
        for operation_id in self._event_store.stream_ids(OPERATION_STREAM_TYPE):
            stored, _version = await self._event_store.load(OPERATION_STREAM_TYPE, operation_id)
            operation = fold([from_stored(row) for row in stored])
            if operation is None:
                continue
            summaries.append(
                OperationSummary(
                    operation_id=operation.id,
                    name=operation.name,
                    created_at=stored[0].occurred_at,
                )
            )
        return summaries


__all__ = ["InMemoryOperationSummaryLookup"]
