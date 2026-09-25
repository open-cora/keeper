"""Answer the same questions by folding, when there is no table to read.

The in-memory half of the `PlanSummaryLookup` port, and the run lookup's
sibling. Same reason for existing: this application boots and answers with
no database, which is what the unit and contract tiers run against, and in
that environment no projection worker runs so the table the other adapter
reads never fills.

Same trade too. Every plan stream, folded, sorted, filtered, paged, which
is the cost a projection exists to avoid and is free when the store is a
dictionary. `tests/_port_contracts/plan_summary_lookup.py` is what makes
"the two answer alike" a checkable claim rather than a hopeful one.
"""

from keeper.execution.aggregates.plan.events import from_stored
from keeper.execution.aggregates.plan.evolver import fold
from keeper.execution.aggregates.plan.read import PLAN_STREAM_TYPE
from keeper.execution.aggregates.plan.state import PlanName
from keeper.execution.aggregates.plan.summary import PlanSummary, PlanSummaryPage
from keeper.infrastructure.adapters.in_memory_event_store import InMemoryEventStore
from keeper.infrastructure.projection.cursor import decode_cursor, encode_cursor


class InMemoryPlanSummaryLookup:
    """Fold-everything implementation of the `PlanSummaryLookup` port.

    Typed against the concrete in-memory store rather than the
    `EventStore` port, because enumerating streams is not something the
    port offers and should not become something it offers.
    """

    def __init__(self, event_store: InMemoryEventStore) -> None:
        self._event_store = event_store

    async def list_plans(
        self,
        *,
        name: PlanName | None,
        limit: int,
        cursor: str | None,
    ) -> PlanSummaryPage:
        """Return one page of plans, newest first."""
        summaries = [
            summary
            for summary in await self._all_summaries()
            if name is None or summary.name == name
        ]
        summaries.sort(key=lambda summary: (summary.created_at, summary.plan_id), reverse=True)

        after = decode_cursor(cursor) if cursor is not None else None
        if after is not None:
            summaries = [
                summary for summary in summaries if (summary.created_at, summary.plan_id) < after
            ]

        page, has_more = summaries[:limit], len(summaries) > limit
        next_cursor = (
            encode_cursor(created_at=page[-1].created_at, item_id=page[-1].plan_id)
            if has_more and page
            else None
        )
        return PlanSummaryPage(items=page, next_cursor=next_cursor)

    async def _all_summaries(self) -> list[PlanSummary]:
        """Fold every plan stream into the row a projection would write.

        `created_at` comes off the envelope, which for a plan is the only
        event there is, so there is no first-and-last pair to keep
        straight the way the run side has.
        """
        summaries: list[PlanSummary] = []
        for plan_id in self._event_store.stream_ids(PLAN_STREAM_TYPE):
            stored, _version = await self._event_store.load(PLAN_STREAM_TYPE, plan_id)
            plan = fold([from_stored(row) for row in stored])
            if plan is None:
                continue
            summaries.append(
                PlanSummary(
                    plan_id=plan.id,
                    name=plan.name,
                    created_at=stored[0].occurred_at,
                )
            )
        return summaries


__all__ = ["InMemoryPlanSummaryLookup"]
