"""Answer the same question by folding, when there is no table to read.

The in-memory half of the `ExecutionSummaryLookup` port. It exists because
this application is meant to boot and answer with no database at all,
which is what the unit and contract tiers run against. In that
environment no projection worker runs, so the table the other adapter
reads does not exist and never fills.

So this one recomputes. Every execution stream, folded, sorted, filtered,
paged. That is precisely the cost a projection exists to avoid, and it
is the right trade here: the store is a dictionary, the streams number
in the tens, and the alternative is a surface that works in production
and refuses in every test.

## Why the two halves can be trusted to agree

They cannot, on inspection.
`tests/_port_contracts/execution_summary_lookup.py` is one suite run against
both, which is the only thing that makes the claim checkable.

The fold reaches the progress count a different way than the table
does, which is worth knowing when one of them is wrong. Here it counts
the steps the evolver marked reported; there it reads the size of a set
the projection unioned into. Two routes to one number is what the
contract suite is comparing.
"""

from uuid import UUID

from keeper.execution.aggregates.execution.events import from_stored
from keeper.execution.aggregates.execution.evolver import fold
from keeper.execution.aggregates.execution.read import EXECUTION_STREAM_TYPE
from keeper.execution.aggregates.execution.state import ExecutionBeamline, ExecutionStatus
from keeper.execution.aggregates.execution.summary import ExecutionSummary, ExecutionSummaryPage
from keeper.infrastructure.adapters.in_memory_event_store import InMemoryEventStore
from keeper.infrastructure.projection.cursor import decode_cursor, encode_cursor


class InMemoryExecutionSummaryLookup:
    """Fold-everything implementation of the `ExecutionSummaryLookup` port.

    Typed against the concrete in-memory store rather than the
    `EventStore` port, because enumerating streams is not something the
    port offers and should not become something it offers.
    """

    def __init__(self, event_store: InMemoryEventStore) -> None:
        self._event_store = event_store

    async def list_executions(
        self,
        *,
        procedure_id: UUID | None,
        beamline: ExecutionBeamline | None,
        status: ExecutionStatus | None,
        limit: int,
        cursor: str | None,
    ) -> ExecutionSummaryPage:
        """Return one page of executions, newest first."""
        summaries = [
            summary
            for summary in await self._all_summaries()
            if (procedure_id is None or summary.procedure_id == procedure_id)
            and (beamline is None or summary.beamline == beamline)
            and (status is None or summary.status is status)
        ]
        summaries.sort(key=lambda summary: (summary.created_at, summary.execution_id), reverse=True)

        after = decode_cursor(cursor) if cursor is not None else None
        if after is not None:
            summaries = [
                summary
                for summary in summaries
                if (summary.created_at, summary.execution_id) < after
            ]

        page, has_more = summaries[:limit], len(summaries) > limit
        next_cursor = (
            encode_cursor(created_at=page[-1].created_at, item_id=page[-1].execution_id)
            if has_more and page
            else None
        )
        return ExecutionSummaryPage(items=page, next_cursor=next_cursor)

    async def _all_summaries(self) -> list[ExecutionSummary]:
        """Fold every execution stream into the row a projection would have written.

        `created_at` is the first event's domain time and `updated_at`
        the largest of them, which is not the same as the last one's. A
        driver may report a step late, and the table takes the greater
        of the two for that reason, so taking the last here would put
        the two halves of this port one row apart.
        """
        summaries: list[ExecutionSummary] = []
        for execution_id in self._event_store.stream_ids(EXECUTION_STREAM_TYPE):
            stored, _version = await self._event_store.load(EXECUTION_STREAM_TYPE, execution_id)
            execution = fold([from_stored(row) for row in stored])
            if execution is None:
                continue
            summaries.append(
                ExecutionSummary(
                    execution_id=execution.id,
                    procedure_id=execution.procedure_id,
                    procedure_name=execution.procedure_name.value,
                    beamline=execution.beamline,
                    step_count=execution.step_count,
                    reported_count=execution.reported_count,
                    status=execution.status,
                    created_at=stored[0].occurred_at,
                    updated_at=max(row.occurred_at for row in stored),
                )
            )
        return summaries


__all__ = ["InMemoryExecutionSummaryLookup"]
