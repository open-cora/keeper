"""Answer the same question by folding, when there is no table to read.

The in-memory half of the `DeviceSummaryLookup` port. It exists because
this application is meant to boot and answer with no database at all,
which is what the unit and contract tiers run against. In that
environment no projection worker runs, so the table the other adapter
reads does not exist and never fills.

So this one recomputes. Every device stream, folded, filtered, sorted,
paged. That is precisely the cost a projection exists to avoid, and it
is the right trade here: the store is a dictionary, the streams number
in the tens, and the alternative is a surface that works in production
and refuses in every test.

## Why the two halves can be trusted to agree

They cannot, on inspection.
`tests/_port_contracts/device_summary_lookup.py` is one suite run
against both, which is the only thing that makes the claim checkable,
and `test_port_contracts_have_two_sides.py` fails if the second driver
ever goes away.

That suite is load-bearing for more than paging here. The status is
derived twice in this context, once by the evolver and once by the
projection's own map, and this adapter reads the evolver's answer while
its partner reads the projection's. A disagreement between those two
derivations shows up as a contract failure, which is the only place it
could show up at all.

The one thing this cannot reproduce is lag. A projection is eventually
consistent and this is immediate, so a test that passes here says
nothing about a caller reading too soon. That is the integration tier's
job, and `drain_projections` is how it asks the question without
sleeping.

## Where the two timestamps come from

`registered_at` is the envelope of the genesis event and `updated_at`
the envelope of the last event on the stream, which is what the
projection's two statements write. A device that has never moved has one
event, so both read the same row and match the genesis-only case the
other adapter produces by writing the same value into both columns.
"""

from keeper.equipment.aggregates.device.events import from_stored
from keeper.equipment.aggregates.device.evolver import fold
from keeper.equipment.aggregates.device.read import DEVICE_STREAM_TYPE
from keeper.equipment.aggregates.device.state import DeviceStatus
from keeper.equipment.aggregates.device.summary import DeviceSummary, DeviceSummaryPage
from keeper.infrastructure.adapters.in_memory_event_store import InMemoryEventStore
from keeper.infrastructure.projection.cursor import decode_cursor, encode_cursor
from keeper.shared.identifier import Identifier


class InMemoryDeviceSummaryLookup:
    """Fold-everything implementation of the `DeviceSummaryLookup` port.

    Typed against the concrete in-memory store rather than the
    `EventStore` port, because enumerating streams is not something the
    port offers and should not become something it offers. An adapter
    for the in-memory environment depending on the in-memory store is
    honest about what it is.
    """

    def __init__(self, event_store: InMemoryEventStore) -> None:
        self._event_store = event_store

    async def list_devices(
        self,
        *,
        external_ref: Identifier | None,
        status: DeviceStatus | None,
        limit: int,
        cursor: str | None,
    ) -> DeviceSummaryPage:
        """Return one page of devices, newest first."""
        summaries = [
            summary
            for summary in await self._all_summaries()
            if (external_ref is None or summary.external_ref == external_ref)
            and (status is None or summary.status is status)
        ]
        summaries.sort(key=lambda summary: (summary.registered_at, summary.device_id), reverse=True)

        after = decode_cursor(cursor) if cursor is not None else None
        if after is not None:
            summaries = [
                summary
                for summary in summaries
                if (summary.registered_at, summary.device_id) < after
            ]

        page, has_more = summaries[:limit], len(summaries) > limit
        next_cursor = (
            encode_cursor(created_at=page[-1].registered_at, item_id=page[-1].device_id)
            if has_more and page
            else None
        )
        return DeviceSummaryPage(items=page, next_cursor=next_cursor)

    async def _all_summaries(self) -> list[DeviceSummary]:
        """Fold every device stream into the row a projection would write."""
        summaries: list[DeviceSummary] = []
        for device_id in self._event_store.stream_ids(DEVICE_STREAM_TYPE):
            stored, _version = await self._event_store.load(DEVICE_STREAM_TYPE, device_id)
            device = fold([from_stored(row) for row in stored])
            if device is None:
                continue
            summaries.append(
                DeviceSummary(
                    device_id=device.id,
                    external_ref=device.external_ref,
                    name=device.name.value,
                    status=device.status,
                    registered_at=stored[0].occurred_at,
                    updated_at=stored[-1].occurred_at,
                )
            )
        return summaries


__all__ = ["InMemoryDeviceSummaryLookup"]
