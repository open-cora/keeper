"""Answer the same question by folding, when there is no table to read.

The in-memory half of the `InquirySummaryLookup` port. It exists because
this application is meant to boot and answer with no database at all, which
is what the unit and contract tiers run against. In that environment no
projection worker runs, so the table the other adapter reads does not exist
and never fills.

So this one recomputes. Every inquiry stream, folded, filtered, sorted,
paged. That is precisely the cost a projection exists to avoid, and it is
the right trade here: the store is a dictionary, the streams number in the
tens, and the alternative is a surface that works in production and refuses
in every test.

## Why the two halves can be trusted to agree

They cannot, on inspection.
`tests/_port_contracts/inquiry_summary_lookup.py` is one suite run against
both, which is the only thing that makes the claim checkable, and
`test_port_contracts_have_two_sides.py` fails if the second driver ever goes
away.

The status is the place they could most easily drift. Here it comes off the
fold, which reads it from which events landed; over there it is derived from
two nullable columns. Both spell the same rule and neither can see the
other.

The one thing this cannot reproduce is lag. A projection is eventually
consistent and this is immediate, so a test that passes here says nothing
about a caller reading too soon. That is the integration tier's job, and
`drain_projections` is how it asks the question without sleeping.

## Where the three timestamps come from

The envelope of the first event, of the claim, and of the answer, which is
what the projection's three statements write. Reading them off the envelope
rather than the payload keeps this adapter agreeing with the other one about
which value is which, since the projection has no access to anything else
either.
"""

from keeper.counsel.aggregates.inquiry.events import from_stored
from keeper.counsel.aggregates.inquiry.evolver import fold
from keeper.counsel.aggregates.inquiry.read import INQUIRY_STREAM_TYPE
from keeper.counsel.aggregates.inquiry.state import InquiryStatus
from keeper.counsel.aggregates.inquiry.summary import InquirySummary, InquirySummaryPage
from keeper.infrastructure.adapters.in_memory_event_store import InMemoryEventStore
from keeper.infrastructure.projection.cursor import decode_cursor, encode_cursor

_CLAIMED_EVENT_TYPE = "InquiryClaimed"
_ANSWERED_EVENT_TYPE = "InquiryAnswered"


class InMemoryInquirySummaryLookup:
    """Fold-everything implementation of the `InquirySummaryLookup` port.

    Typed against the concrete in-memory store rather than the `EventStore`
    port, because enumerating streams is not something the port offers and
    should not become something it offers. An adapter for the in-memory
    environment depending on the in-memory store is honest about what it is.
    """

    def __init__(self, event_store: InMemoryEventStore) -> None:
        self._event_store = event_store

    async def list_inquiries(
        self,
        *,
        status: InquiryStatus | None,
        limit: int,
        cursor: str | None,
    ) -> InquirySummaryPage:
        """Return one page of inquiries, newest first."""
        summaries = [
            summary
            for summary in await self._all_summaries()
            if status is None or summary.status is status
        ]
        summaries.sort(key=lambda summary: (summary.created_at, summary.inquiry_id), reverse=True)

        after = decode_cursor(cursor) if cursor is not None else None
        if after is not None:
            summaries = [
                summary for summary in summaries if (summary.created_at, summary.inquiry_id) < after
            ]

        page, has_more = summaries[:limit], len(summaries) > limit
        next_cursor = (
            encode_cursor(created_at=page[-1].created_at, item_id=page[-1].inquiry_id)
            if has_more and page
            else None
        )
        return InquirySummaryPage(items=page, next_cursor=next_cursor)

    async def _all_summaries(self) -> list[InquirySummary]:
        """Fold every inquiry stream into the row a projection would write."""
        summaries: list[InquirySummary] = []
        for inquiry_id in self._event_store.stream_ids(INQUIRY_STREAM_TYPE):
            stored, _version = await self._event_store.load(INQUIRY_STREAM_TYPE, inquiry_id)
            inquiry = fold([from_stored(row) for row in stored])
            if inquiry is None:
                continue
            claimed_at = next(
                (row.occurred_at for row in stored if row.event_type == _CLAIMED_EVENT_TYPE),
                None,
            )
            answered_at = next(
                (row.occurred_at for row in stored if row.event_type == _ANSWERED_EVENT_TYPE),
                None,
            )
            summaries.append(
                InquirySummary(
                    inquiry_id=inquiry.id,
                    actor_id=inquiry.actor_id,
                    execution_id=inquiry.execution_id,
                    objective=inquiry.objective.value,
                    execution_step_count=inquiry.execution_step_count,
                    status=inquiry.status,
                    conclusion=inquiry.conclusion,
                    observed_step_count=inquiry.observed_step_count,
                    execution_ended=inquiry.execution_ended,
                    proposal_id=inquiry.proposal_id,
                    created_at=stored[0].occurred_at,
                    claimed_at=claimed_at,
                    answered_at=answered_at,
                )
            )
        return summaries


__all__ = ["InMemoryInquirySummaryLookup"]
