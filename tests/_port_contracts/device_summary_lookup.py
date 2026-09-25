"""Behaviour every `DeviceSummaryLookup` adapter owes its callers.

The fifth summary contract, and the same reason for existing as the four
beside it: one side reads a table a worker maintains, the other folds
every stream, and nothing about the code on one resembles the other.

Two things are new here, and the first is the reason this suite carries
more weight than its siblings.

**The status is derived twice.** The evolver computes it from the event
type, and the projection computes it again from its own map. The
in-memory adapter reads the first and the Postgres adapter reads the
second, so a disagreement between the two derivations is invisible
everywhere except here. Every check below that asserts a status is
therefore checking agreement between two pieces of code that never call
each other, which is why the transitions are exercised one at a time
rather than folded into a single path.

**There are two filters and they combine.** Three states in each, since
both are nullable, so a check that only exercised the set cases would
leave the unfiltered default untested on both sides. The address filter
is the one an adapter cannot work without, so it is pinned including the
case the write side permits and nobody wants: two devices at one
address.
"""

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID, uuid4

import pytest

from keeper.equipment.aggregates.device.state import DeviceStatus
from keeper.equipment.aggregates.device.summary import DeviceSummaryLookup
from keeper.infrastructure.projection.cursor import InvalidCursorError, encode_cursor
from keeper.shared.identifier import Identifier


class DeviceWriter(Protocol):
    """Put devices where the adapter under test will find them."""

    async def register(
        self,
        *,
        device_id: UUID,
        external_ref: Identifier,
        device_name: str,
        at: datetime,
    ) -> None:
        """Enrol a device."""
        ...

    async def fault(self, *, device_id: UUID, at: datetime) -> None:
        """Report that it faulted."""
        ...

    async def recover(self, *, device_id: UUID, at: datetime) -> None:
        """Report that it came back."""
        ...

    async def retire(self, *, device_id: UUID, at: datetime) -> None:
        """Stop counting it."""
        ...


Check = Callable[[DeviceSummaryLookup, DeviceWriter], Awaitable[None]]
"""One behaviour, applied to whichever adapter the driver supplies."""

_EPOCH = datetime(2026, 3, 1, 9, 0, tzinfo=UTC)
"""A fixed instant the checks below count minutes from.

Fixed rather than `now`, so an ordering assertion reads as an ordering
rather than as arithmetic on the wall clock.
"""

_PAGE = 50
"""A limit wide enough that paging does not interfere with other checks."""

_SCHEME = "example-control"
"""An addressing vocabulary with no product behind it.

The scheme is opaque to this system, so a contract suite has no reason
to spell a real one and every reason not to: a rule stated for one
control system reads as a rule derived from one.
"""


def _at(minute: int) -> datetime:
    return _EPOCH + timedelta(minutes=minute)


async def _one_device(
    writer: DeviceWriter,
    *,
    minute: int,
    value: str | None = None,
    device_name: str = "a device",
) -> UUID:
    device_id = uuid4()
    await writer.register(
        device_id=device_id,
        external_ref=Identifier(scheme=_SCHEME, value=value or str(uuid4())),
        device_name=device_name,
        at=_at(minute),
    )
    return device_id


async def check_an_empty_read_model_returns_an_empty_page(
    lookup: DeviceSummaryLookup, writer: DeviceWriter
) -> None:
    _ = writer
    page = await lookup.list_devices(external_ref=None, status=None, limit=_PAGE, cursor=None)
    assert page.items == []
    assert page.next_cursor is None


async def check_a_new_device_shows_with_its_address_label_and_time(
    lookup: DeviceSummaryLookup, writer: DeviceWriter
) -> None:
    reference = Identifier(scheme=_SCHEME, value="station-1:m1")
    device_id = uuid4()
    await writer.register(
        device_id=device_id,
        external_ref=reference,
        device_name="sample x translation",
        at=_EPOCH,
    )

    page = await lookup.list_devices(external_ref=None, status=None, limit=_PAGE, cursor=None)

    (summary,) = page.items
    assert summary.device_id == device_id
    assert summary.external_ref == reference
    assert summary.name == "sample x translation"
    assert summary.registered_at == _EPOCH


async def check_a_new_device_is_available(
    lookup: DeviceSummaryLookup, writer: DeviceWriter
) -> None:
    """The genesis status, derived on one side by the fold and on the other
    by the projection, and the two have to agree."""
    await _one_device(writer, minute=0)

    page = await lookup.list_devices(external_ref=None, status=None, limit=_PAGE, cursor=None)

    (summary,) = page.items
    assert summary.status is DeviceStatus.AVAILABLE


async def check_a_device_that_never_moved_was_updated_when_it_was_registered(
    lookup: DeviceSummaryLookup, writer: DeviceWriter
) -> None:
    """One column carries a real value rather than a null a reader has to
    interpret, which the two adapters reach by different routes: one writes
    the registration time into both columns, the other reads the first and
    last event of a one-event stream."""
    await _one_device(writer, minute=0)

    page = await lookup.list_devices(external_ref=None, status=None, limit=_PAGE, cursor=None)

    (summary,) = page.items
    assert summary.updated_at == summary.registered_at == _EPOCH


async def check_a_faulted_device_reads_as_faulted_at_the_reported_time(
    lookup: DeviceSummaryLookup, writer: DeviceWriter
) -> None:
    device_id = await _one_device(writer, minute=0)
    await writer.fault(device_id=device_id, at=_at(5))

    page = await lookup.list_devices(external_ref=None, status=None, limit=_PAGE, cursor=None)

    (summary,) = page.items
    assert summary.status is DeviceStatus.FAULTED
    assert summary.updated_at == _at(5)


async def check_a_recovered_device_reads_as_available_again(
    lookup: DeviceSummaryLookup, writer: DeviceWriter
) -> None:
    """The one transition that returns to a status the device already held,
    so a projection that only ever moved forward would fail here."""
    device_id = await _one_device(writer, minute=0)
    await writer.fault(device_id=device_id, at=_at(5))
    await writer.recover(device_id=device_id, at=_at(9))

    page = await lookup.list_devices(external_ref=None, status=None, limit=_PAGE, cursor=None)

    (summary,) = page.items
    assert summary.status is DeviceStatus.AVAILABLE
    assert summary.updated_at == _at(9)


async def check_a_retired_device_reads_as_retired(
    lookup: DeviceSummaryLookup, writer: DeviceWriter
) -> None:
    device_id = await _one_device(writer, minute=0)
    await writer.retire(device_id=device_id, at=_at(3))

    page = await lookup.list_devices(external_ref=None, status=None, limit=_PAGE, cursor=None)

    (summary,) = page.items
    assert summary.status is DeviceStatus.RETIRED


async def check_a_faulted_device_can_be_retired_without_recovering_first(
    lookup: DeviceSummaryLookup, writer: DeviceWriter
) -> None:
    """The ordinary way a broken thing leaves a register, and a path a
    projection written as a forward-only chain would get wrong."""
    device_id = await _one_device(writer, minute=0)
    await writer.fault(device_id=device_id, at=_at(1))
    await writer.retire(device_id=device_id, at=_at(2))

    page = await lookup.list_devices(external_ref=None, status=None, limit=_PAGE, cursor=None)

    (summary,) = page.items
    assert summary.status is DeviceStatus.RETIRED


async def check_a_transition_does_not_move_when_the_device_was_registered(
    lookup: DeviceSummaryLookup, writer: DeviceWriter
) -> None:
    """Two timestamps from two authorities, and the second must not overwrite
    the first: a list is ordered by when a device was enrolled."""
    device_id = await _one_device(writer, minute=0)
    await writer.fault(device_id=device_id, at=_at(5))

    page = await lookup.list_devices(external_ref=None, status=None, limit=_PAGE, cursor=None)

    assert page.items[0].registered_at == _EPOCH


async def check_the_address_filter_returns_only_the_device_at_that_address(
    lookup: DeviceSummaryLookup, writer: DeviceWriter
) -> None:
    """The resolution every adapter makes before it can report anything."""
    wanted = await _one_device(writer, minute=0, value="station-1:m1")
    await _one_device(writer, minute=1, value="station-1:m2")

    page = await lookup.list_devices(
        external_ref=Identifier(scheme=_SCHEME, value="station-1:m1"),
        status=None,
        limit=_PAGE,
        cursor=None,
    )

    assert [summary.device_id for summary in page.items] == [wanted]


async def check_the_address_filter_matches_the_scheme_as_well_as_the_value(
    lookup: DeviceSummaryLookup, writer: DeviceWriter
) -> None:
    """A value is opaque within its scheme, so two schemes can spell one
    string and mean different things."""
    device_id = uuid4()
    await writer.register(
        device_id=device_id,
        external_ref=Identifier(scheme="other-control", value="station-1:m1"),
        device_name="a device",
        at=_EPOCH,
    )

    page = await lookup.list_devices(
        external_ref=Identifier(scheme=_SCHEME, value="station-1:m1"),
        status=None,
        limit=_PAGE,
        cursor=None,
    )

    assert page.items == []


async def check_two_devices_at_one_address_both_come_back(
    lookup: DeviceSummaryLookup, writer: DeviceWriter
) -> None:
    """Nothing on the write side stops this, so the read side has to show it
    rather than hide it behind a lookup that can only answer once. A caller
    resolving an address is about to write to whatever comes back."""
    first = await _one_device(writer, minute=0, value="station-1:m1")
    second = await _one_device(writer, minute=1, value="station-1:m1")

    page = await lookup.list_devices(
        external_ref=Identifier(scheme=_SCHEME, value="station-1:m1"),
        status=None,
        limit=_PAGE,
        cursor=None,
    )

    assert {summary.device_id for summary in page.items} == {first, second}


async def check_the_status_filter_returns_only_devices_in_that_state(
    lookup: DeviceSummaryLookup, writer: DeviceWriter
) -> None:
    await _one_device(writer, minute=0)
    faulted = await _one_device(writer, minute=1)
    await writer.fault(device_id=faulted, at=_at(2))

    page = await lookup.list_devices(
        external_ref=None, status=DeviceStatus.FAULTED, limit=_PAGE, cursor=None
    )

    assert [summary.device_id for summary in page.items] == [faulted]


async def check_a_device_leaves_the_faulted_side_once_it_recovers(
    lookup: DeviceSummaryLookup, writer: DeviceWriter
) -> None:
    """A row moving between filters in both directions, which no other
    summary in this tree does: a proposal that has been taken stays taken."""
    device_id = await _one_device(writer, minute=0)
    await writer.fault(device_id=device_id, at=_at(1))
    while_faulted = await lookup.list_devices(
        external_ref=None, status=DeviceStatus.FAULTED, limit=_PAGE, cursor=None
    )

    await writer.recover(device_id=device_id, at=_at(2))
    after = await lookup.list_devices(
        external_ref=None, status=DeviceStatus.FAULTED, limit=_PAGE, cursor=None
    )

    assert [summary.device_id for summary in while_faulted.items] == [device_id]
    assert after.items == []


async def check_no_filter_returns_every_status(
    lookup: DeviceSummaryLookup, writer: DeviceWriter
) -> None:
    """The default, and the state a filter without a null would leave
    untested."""
    available = await _one_device(writer, minute=0)
    faulted = await _one_device(writer, minute=1)
    retired = await _one_device(writer, minute=2)
    await writer.fault(device_id=faulted, at=_at(3))
    await writer.retire(device_id=retired, at=_at(4))

    page = await lookup.list_devices(external_ref=None, status=None, limit=_PAGE, cursor=None)

    assert {summary.device_id for summary in page.items} == {available, faulted, retired}


async def check_the_two_filters_combine(lookup: DeviceSummaryLookup, writer: DeviceWriter) -> None:
    """Asking for a faulted device at an address is one call, which is what
    a reporter holding an address and seeing an alarm actually asks."""
    faulted_here = await _one_device(writer, minute=0, value="station-1:m1")
    await _one_device(writer, minute=1, value="station-1:m1")
    elsewhere = await _one_device(writer, minute=2, value="station-1:m2")
    await writer.fault(device_id=faulted_here, at=_at(3))
    await writer.fault(device_id=elsewhere, at=_at(4))

    page = await lookup.list_devices(
        external_ref=Identifier(scheme=_SCHEME, value="station-1:m1"),
        status=DeviceStatus.FAULTED,
        limit=_PAGE,
        cursor=None,
    )

    assert [summary.device_id for summary in page.items] == [faulted_here]


async def check_nothing_faulted_returns_an_empty_page(
    lookup: DeviceSummaryLookup, writer: DeviceWriter
) -> None:
    await _one_device(writer, minute=0)

    page = await lookup.list_devices(
        external_ref=None, status=DeviceStatus.FAULTED, limit=_PAGE, cursor=None
    )

    assert page.items == []
    assert page.next_cursor is None


async def check_devices_come_back_newest_first(
    lookup: DeviceSummaryLookup, writer: DeviceWriter
) -> None:
    oldest = await _one_device(writer, minute=0)
    middle = await _one_device(writer, minute=1)
    newest = await _one_device(writer, minute=2)

    page = await lookup.list_devices(external_ref=None, status=None, limit=_PAGE, cursor=None)

    assert [summary.device_id for summary in page.items] == [newest, middle, oldest]


async def check_ordering_is_on_registration_and_a_fault_does_not_reorder(
    lookup: DeviceSummaryLookup, writer: DeviceWriter
) -> None:
    """A keyset cursor needs a key that does not move, so the page is ordered
    on the one column that cannot: faulting the oldest device must not carry
    it to the front."""
    oldest = await _one_device(writer, minute=0)
    newest = await _one_device(writer, minute=1)
    await writer.fault(device_id=oldest, at=_at(9))

    page = await lookup.list_devices(external_ref=None, status=None, limit=_PAGE, cursor=None)

    assert [summary.device_id for summary in page.items] == [newest, oldest]


async def check_a_full_page_hands_back_a_cursor_that_continues_it(
    lookup: DeviceSummaryLookup, writer: DeviceWriter
) -> None:
    oldest = await _one_device(writer, minute=0)
    newest = await _one_device(writer, minute=1)

    first = await lookup.list_devices(external_ref=None, status=None, limit=1, cursor=None)
    assert [summary.device_id for summary in first.items] == [newest]
    assert first.next_cursor is not None

    second = await lookup.list_devices(
        external_ref=None, status=None, limit=1, cursor=first.next_cursor
    )
    assert [summary.device_id for summary in second.items] == [oldest]


async def check_the_last_page_hands_back_no_cursor(
    lookup: DeviceSummaryLookup, writer: DeviceWriter
) -> None:
    await _one_device(writer, minute=0)

    page = await lookup.list_devices(external_ref=None, status=None, limit=1, cursor=None)

    assert page.next_cursor is None


async def check_a_cursor_narrows_within_a_filter(
    lookup: DeviceSummaryLookup, writer: DeviceWriter
) -> None:
    """Paging and filtering have to compose, or the second page of a filtered
    list quietly widens to the whole table."""
    older_faulted = await _one_device(writer, minute=0)
    newer_faulted = await _one_device(writer, minute=1)
    available = await _one_device(writer, minute=2)
    await writer.fault(device_id=older_faulted, at=_at(3))
    await writer.fault(device_id=newer_faulted, at=_at(4))

    first = await lookup.list_devices(
        external_ref=None, status=DeviceStatus.FAULTED, limit=1, cursor=None
    )
    assert [summary.device_id for summary in first.items] == [newer_faulted]
    assert first.next_cursor is not None

    second = await lookup.list_devices(
        external_ref=None, status=DeviceStatus.FAULTED, limit=1, cursor=first.next_cursor
    )
    assert [summary.device_id for summary in second.items] == [older_faulted]
    assert available not in {summary.device_id for summary in second.items}


async def check_devices_registered_at_one_instant_page_without_repeating_or_skipping(
    lookup: DeviceSummaryLookup, writer: DeviceWriter
) -> None:
    """A register is normally filled in one pass, by a script enrolling every
    device on a station, so this tie is the common case rather than the
    exotic one. The id in the sort key is what breaks it the same way on
    every page."""
    ids = {await _one_device(writer, minute=0) for _ in range(5)}

    seen: list[UUID] = []
    cursor: str | None = None
    while True:
        page = await lookup.list_devices(external_ref=None, status=None, limit=2, cursor=cursor)
        seen.extend(summary.device_id for summary in page.items)
        cursor = page.next_cursor
        if cursor is None:
            break

    assert len(seen) == len(set(seen)) == len(ids)
    assert set(seen) == ids


async def check_a_cursor_that_did_not_come_from_a_response_is_refused(
    lookup: DeviceSummaryLookup, writer: DeviceWriter
) -> None:
    _ = writer
    with pytest.raises(InvalidCursorError):
        await lookup.list_devices(
            external_ref=None, status=None, limit=_PAGE, cursor="not-a-cursor"
        )


async def check_a_cursor_past_the_end_returns_an_empty_page(
    lookup: DeviceSummaryLookup, writer: DeviceWriter
) -> None:
    await _one_device(writer, minute=5)

    page = await lookup.list_devices(
        external_ref=None,
        status=None,
        limit=_PAGE,
        cursor=encode_cursor(created_at=_EPOCH, item_id=UUID(int=0)),
    )

    assert page.items == []
    assert page.next_cursor is None


CHECKS: tuple[Check, ...] = (
    check_an_empty_read_model_returns_an_empty_page,
    check_a_new_device_shows_with_its_address_label_and_time,
    check_a_new_device_is_available,
    check_a_device_that_never_moved_was_updated_when_it_was_registered,
    check_a_faulted_device_reads_as_faulted_at_the_reported_time,
    check_a_recovered_device_reads_as_available_again,
    check_a_retired_device_reads_as_retired,
    check_a_faulted_device_can_be_retired_without_recovering_first,
    check_a_transition_does_not_move_when_the_device_was_registered,
    check_the_address_filter_returns_only_the_device_at_that_address,
    check_the_address_filter_matches_the_scheme_as_well_as_the_value,
    check_two_devices_at_one_address_both_come_back,
    check_the_status_filter_returns_only_devices_in_that_state,
    check_a_device_leaves_the_faulted_side_once_it_recovers,
    check_no_filter_returns_every_status,
    check_the_two_filters_combine,
    check_nothing_faulted_returns_an_empty_page,
    check_devices_come_back_newest_first,
    check_ordering_is_on_registration_and_a_fault_does_not_reorder,
    check_a_full_page_hands_back_a_cursor_that_continues_it,
    check_the_last_page_hands_back_no_cursor,
    check_a_cursor_narrows_within_a_filter,
    check_devices_registered_at_one_instant_page_without_repeating_or_skipping,
    check_a_cursor_that_did_not_come_from_a_response_is_refused,
    check_a_cursor_past_the_end_returns_an_empty_page,
)
"""Every check above. Hand-written; the drivers guard against omissions."""


def checks_defined_but_not_listed() -> frozenset[str]:
    """Check functions defined in this module that `CHECKS` leaves out.

    The tuple is the contract; a function absent from it runs nowhere.
    """
    listed = {check.__name__ for check in CHECKS}
    defined = {
        name for name, value in globals().items() if name.startswith("check_") and callable(value)
    }
    return frozenset(defined - listed)


__all__ = ["CHECKS", "Check", "DeviceWriter", "checks_defined_but_not_listed"]
