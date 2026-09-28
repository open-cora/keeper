"""Answer the same question by folding, when there is no table to read.

The in-memory half of the `PursuitSummaryLookup` port. It exists because
this application is meant to boot and answer with no database at all,
which is what the unit and contract tiers run against. In that environment
no projection worker runs, so the table the other adapter reads does not
exist and never fills.

So this one recomputes. Every pursuit stream, folded, filtered, sorted,
paged. That is precisely the cost a projection exists to avoid, and it is
the right trade here: the store is a dictionary, the streams number in the
tens, and the alternative is a surface that works in production and
refuses in every test.

## Why the two halves can be trusted to agree

They cannot, on inspection.
`tests/_port_contracts/pursuit_summary_lookup.py` is one suite run against
both, which is the only thing that makes the claim checkable, and
`test_port_contracts_have_two_sides.py` fails if the second driver ever
goes away.

That matters more for this port than for its siblings. The others derive
their status on both sides from the same nullable columns, so the two
spellings are close to each other by construction. Here the fold sets a
status from which arm ran and the table stores one the projection wrote,
and the two could drift without either being obviously wrong.

The one thing this cannot reproduce is lag. A projection is eventually
consistent and this is immediate, so a test that passes here says nothing
about a caller reading too soon. That is the integration tier's job.

## Where the two timestamps come from

`created_at` is the envelope of the genesis, and `stopped_at` the envelope
of the withdrawal when there was one. A pursuit that stopped because a
thinker said so has no `stopped_at`, which matches what the projection
writes: only the withdrawing arm sets that column, because only a person
stopping a loop is an event about the loop ending rather than about a
round.
"""

from keeper.infrastructure.adapters.in_memory_event_store import InMemoryEventStore
from keeper.infrastructure.projection.cursor import decode_cursor, encode_cursor
from keeper.pursuit.aggregates.pursuit.events import from_stored
from keeper.pursuit.aggregates.pursuit.evolver import fold
from keeper.pursuit.aggregates.pursuit.read import PURSUIT_STREAM_TYPE
from keeper.pursuit.aggregates.pursuit.state import PursuitStatus
from keeper.pursuit.aggregates.pursuit.summary import PursuitSummary, PursuitSummaryPage

_WITHDRAWN_EVENT_TYPE = "PursuitWithdrawn"


class InMemoryPursuitSummaryLookup:
    """Fold-everything implementation of the `PursuitSummaryLookup` port.

    Typed against the concrete in-memory store rather than the `EventStore`
    port, because enumerating streams is not something the port offers and
    should not become something it offers. An adapter for the in-memory
    environment depending on the in-memory store is honest about what it
    is.
    """

    def __init__(self, event_store: InMemoryEventStore) -> None:
        self._event_store = event_store

    async def list_pursuits(
        self,
        *,
        status: PursuitStatus | None,
        beamline: str | None,
        limit: int,
        cursor: str | None,
    ) -> PursuitSummaryPage:
        """Return one page of pursuits, newest first."""
        summaries = [
            summary
            for summary in await self._all_summaries()
            if (status is None or summary.status is status)
            and (beamline is None or summary.beamline == beamline)
        ]
        summaries.sort(key=lambda summary: (summary.created_at, summary.pursuit_id), reverse=True)

        after = decode_cursor(cursor) if cursor is not None else None
        if after is not None:
            summaries = [
                summary for summary in summaries if (summary.created_at, summary.pursuit_id) < after
            ]

        page, has_more = summaries[:limit], len(summaries) > limit
        next_cursor = (
            encode_cursor(created_at=page[-1].created_at, item_id=page[-1].pursuit_id)
            if has_more and page
            else None
        )
        return PursuitSummaryPage(items=page, next_cursor=next_cursor)

    async def _all_summaries(self) -> list[PursuitSummary]:
        """Fold every pursuit stream into the row a projection would write."""
        summaries: list[PursuitSummary] = []
        for pursuit_id in self._event_store.stream_ids(PURSUIT_STREAM_TYPE):
            stored, _version = await self._event_store.load(PURSUIT_STREAM_TYPE, pursuit_id)
            pursuit = fold([from_stored(row) for row in stored])
            if pursuit is None:
                continue
            stopped_at = next(
                (row.occurred_at for row in stored if row.event_type == _WITHDRAWN_EVENT_TYPE),
                None,
            )
            summaries.append(
                PursuitSummary(
                    pursuit_id=pursuit.id,
                    actor_id=pursuit.actor_id,
                    goal=pursuit.goal.value,
                    beamline=pursuit.beamline.value,
                    status=pursuit.status,
                    held_for=pursuit.held_for,
                    round_count=len(pursuit.rounds),
                    created_at=stored[0].occurred_at,
                    stopped_at=stopped_at,
                )
            )
        return summaries


__all__ = ["InMemoryPursuitSummaryLookup"]
