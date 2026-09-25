"""Answer the same questions by folding, when there is no table to read.

The in-memory half of the `ProcedureSummaryLookup` port, and the plan
lookup's sibling. Same reason for existing: this application boots and
answers with no database, which is what the unit and contract tiers run
against, and in that environment no projection worker runs so the table
the other adapter reads never fills.

Same trade too. Every procedure stream, folded, sorted, filtered, paged,
which is the cost a projection exists to avoid and is free when the store
is a dictionary. `tests/_port_contracts/procedure_summary_lookup.py` is
what makes "the two answer alike" a checkable claim rather than a hopeful
one.
"""

from keeper.execution.aggregates.procedure.events import from_stored
from keeper.execution.aggregates.procedure.evolver import fold
from keeper.execution.aggregates.procedure.read import PROCEDURE_STREAM_TYPE
from keeper.execution.aggregates.procedure.state import ProcedureName
from keeper.execution.aggregates.procedure.summary import (
    ProcedureSummary,
    ProcedureSummaryPage,
)
from keeper.infrastructure.adapters.in_memory_event_store import InMemoryEventStore
from keeper.infrastructure.projection.cursor import decode_cursor, encode_cursor


class InMemoryProcedureSummaryLookup:
    """Fold-everything implementation of the `ProcedureSummaryLookup` port.

    Typed against the concrete in-memory store rather than the
    `EventStore` port, because enumerating streams is not something the
    port offers and should not become something it offers.
    """

    def __init__(self, event_store: InMemoryEventStore) -> None:
        self._event_store = event_store

    async def list_procedures(
        self,
        *,
        name: ProcedureName | None,
        limit: int,
        cursor: str | None,
    ) -> ProcedureSummaryPage:
        """Return one page of procedures, newest first."""
        summaries = [
            summary
            for summary in await self._all_summaries()
            if name is None or summary.name == name
        ]
        summaries.sort(key=lambda summary: (summary.created_at, summary.procedure_id), reverse=True)

        after = decode_cursor(cursor) if cursor is not None else None
        if after is not None:
            summaries = [
                summary
                for summary in summaries
                if (summary.created_at, summary.procedure_id) < after
            ]

        page, has_more = summaries[:limit], len(summaries) > limit
        next_cursor = (
            encode_cursor(created_at=page[-1].created_at, item_id=page[-1].procedure_id)
            if has_more and page
            else None
        )
        return ProcedureSummaryPage(items=page, next_cursor=next_cursor)

    async def _all_summaries(self) -> list[ProcedureSummary]:
        """Fold every procedure stream into the row a projection would write.

        `created_at` comes off the envelope, which for a procedure is the
        only event there is, so there is no first-and-last pair to keep
        straight the way the run side has.
        """
        summaries: list[ProcedureSummary] = []
        for procedure_id in self._event_store.stream_ids(PROCEDURE_STREAM_TYPE):
            stored, _version = await self._event_store.load(PROCEDURE_STREAM_TYPE, procedure_id)
            procedure = fold([from_stored(row) for row in stored])
            if procedure is None:
                continue
            summaries.append(
                ProcedureSummary(
                    procedure_id=procedure.id,
                    name=procedure.name,
                    beamline=procedure.beamline,
                    step_count=len(procedure.steps),
                    created_at=stored[0].occurred_at,
                )
            )
        return summaries


__all__ = ["InMemoryProcedureSummaryLookup"]
