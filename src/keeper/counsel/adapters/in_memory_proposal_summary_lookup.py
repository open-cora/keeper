"""Answer the same question by folding, when there is no table to read.

The in-memory half of the `ProposalSummaryLookup` port. It exists
because this application is meant to boot and answer with no database at
all, which is what the unit and contract tiers run against. In that
environment no projection worker runs, so the table the other adapter
reads does not exist and never fills.

So this one recomputes. Every proposal stream, folded, filtered, sorted,
paged. That is precisely the cost a projection exists to avoid, and it is
the right trade here: the store is a dictionary, the streams number in
the tens, and the alternative is a surface that works in production and
refuses in every test.

## Why the two halves can be trusted to agree

They cannot, on inspection.
`tests/_port_contracts/proposal_summary_lookup.py` is one suite run
against both, which is the only thing that makes the claim checkable, and
`test_port_contracts_have_two_sides.py` fails if the second driver ever
goes away.

The one thing this cannot reproduce is lag. A projection is eventually
consistent and this is immediate, so a test that passes here says nothing
about a caller reading too soon. That is the integration tier's job, and
`drain_projections` is how it asks the question without sleeping.

## Where the two timestamps come from

`created_at` is the envelope of the first event and `taken_at` the
envelope of the take, which is what the projection's two statements
write. Reading them off the envelope rather than the payload keeps this
adapter agreeing with the other one about which value is which, since
the projection has no access to anything else either.
"""

from keeper.counsel.aggregates.proposal.events import from_stored
from keeper.counsel.aggregates.proposal.evolver import fold
from keeper.counsel.aggregates.proposal.read import PROPOSAL_STREAM_TYPE
from keeper.counsel.aggregates.proposal.summary import ProposalSummary, ProposalSummaryPage
from keeper.infrastructure.adapters.in_memory_event_store import InMemoryEventStore
from keeper.infrastructure.projection.cursor import decode_cursor, encode_cursor

_TAKEN_EVENT_TYPE = "ProposalTaken"


class InMemoryProposalSummaryLookup:
    """Fold-everything implementation of the `ProposalSummaryLookup` port.

    Typed against the concrete in-memory store rather than the
    `EventStore` port, because enumerating streams is not something the
    port offers and should not become something it offers. An adapter for
    the in-memory environment depending on the in-memory store is honest
    about what it is.
    """

    def __init__(self, event_store: InMemoryEventStore) -> None:
        self._event_store = event_store

    async def list_proposals(
        self,
        *,
        is_open: bool | None,
        limit: int,
        cursor: str | None,
    ) -> ProposalSummaryPage:
        """Return one page of proposals, newest first."""
        summaries = [
            summary
            for summary in await self._all_summaries()
            if is_open is None or (summary.execution_id is None) == is_open
        ]
        summaries.sort(key=lambda summary: (summary.created_at, summary.proposal_id), reverse=True)

        after = decode_cursor(cursor) if cursor is not None else None
        if after is not None:
            summaries = [
                summary
                for summary in summaries
                if (summary.created_at, summary.proposal_id) < after
            ]

        page, has_more = summaries[:limit], len(summaries) > limit
        next_cursor = (
            encode_cursor(created_at=page[-1].created_at, item_id=page[-1].proposal_id)
            if has_more and page
            else None
        )
        return ProposalSummaryPage(items=page, next_cursor=next_cursor)

    async def _all_summaries(self) -> list[ProposalSummary]:
        """Fold every proposal stream into the row a projection would write."""
        summaries: list[ProposalSummary] = []
        for proposal_id in self._event_store.stream_ids(PROPOSAL_STREAM_TYPE):
            stored, _version = await self._event_store.load(PROPOSAL_STREAM_TYPE, proposal_id)
            proposal = fold([from_stored(row) for row in stored])
            if proposal is None:
                continue
            taken_at = next(
                (row.occurred_at for row in stored if row.event_type == _TAKEN_EVENT_TYPE),
                None,
            )
            summaries.append(
                ProposalSummary(
                    proposal_id=proposal.id,
                    actor_id=proposal.actor_id,
                    plan_id=proposal.plan_id,
                    execution_id=proposal.execution_id,
                    step_id=proposal.step_id,
                    created_at=stored[0].occurred_at,
                    taken_at=taken_at,
                )
            )
        return summaries


__all__ = ["InMemoryProposalSummaryLookup"]
