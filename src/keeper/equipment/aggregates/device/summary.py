"""One row per device, and the port that reads those rows.

The other read path. `read.py` rebuilds one device by replaying its
stream, which answers a question that already names the device. The two
questions this context is actually asked name no device at all.

## The two filters, and why each has a caller

The Counsel summary beside this one argues that a filter without a
caller is a column and a parameter earning nothing, and declines three
on those grounds. Both of these have one.

`external_ref` is what makes the context usable by an adapter at all. A
reporter watching a beamline knows the address it is subscribed to and
nothing else: it has no device id, because ids are minted here. So its
first call is always this one, resolving an address to the id it then
faults. That is the same resolution an agent already performs against
the run listing before it can record what took its proposal, and it is
the only way in for a writer that was not the registrar.

`status` is the operator's question, and the one the context exists to
answer: what is faulted right now. It is the counterpart of the run
listing's openness filter rather than a second spelling of it.

## What a summary leaves out

Nothing, which is worth stating because its two siblings both leave out
a field. A run summary drops the parameters and a proposal summary drops
the same, on the grounds that they are unbounded and a page of fifty
rows would be mostly them. A device has no unbounded field: the label is
bounded and everything else is an id, a status or a time. So the summary
is the whole record and a caller reading a list needs no second call.

## The two timestamps

`registered_at` is when this system enrolled the device, and it is never
a caller's claim: enrolling is an act performed here.

`updated_at` is when the last transition landed, and for a fault or a
recovery it MAY be a caller's claim, because those happened at a
beamline. Two timestamps on one row from two authorities is R8 reaching
the read side, the same way it does on a proposal.

There is no separate `faulted_at` column. `status` names which
transition was last, and a column per transition would say the same
thing three more times. A device that has never moved off Available
carries its registration time in both.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from keeper.equipment.aggregates.device.state import DeviceStatus
from keeper.shared.identifier import Identifier


@dataclass(frozen=True)
class DeviceSummary:
    """A device as a list shows it.

    `status` is the derived value, computed by the projection from the
    event type the same way the fold computes it, because a row that
    stored a status a writer could set is a row a writer could set
    wrong.
    """

    device_id: UUID
    external_ref: Identifier
    name: str
    status: DeviceStatus
    registered_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class DeviceSummaryPage:
    """One page of summaries, newest first, and how to ask for the next.

    `next_cursor` is None when this is the last page. It is opaque on
    purpose: it encodes the sort key of the final row, and a caller that
    takes it apart is depending on an ordering this is free to change.
    """

    items: list[DeviceSummary]
    next_cursor: str | None


class DeviceSummaryLookup(Protocol):
    """Read devices by something other than their id.

    Named `Lookup` because that is the shape this repository declares for
    a read port, in `test_port_naming_conventions.py`.
    """

    async def list_devices(
        self,
        *,
        external_ref: Identifier | None,
        status: DeviceStatus | None,
        limit: int,
        cursor: str | None,
    ) -> DeviceSummaryPage:
        """Return one page of devices, newest first.

        `external_ref` narrows to the devices carrying that exact pair.
        Normally none or one, and deliberately not guaranteed to be
        either: nothing stops two records of one address, so a caller
        asking this question has to be able to see both. That is the same
        caveat the run listing carries, and it matters more here, because
        an adapter resolving an address is choosing which device to
        fault.

        `status` narrows to one disposition. The two filters combine, so
        asking for a faulted device at a given address is one call.

        `cursor` continues a previous page and comes from its
        `next_cursor`. A cursor that does not decode raises
        `InvalidCursorError`.
        """
        ...


__all__ = ["DeviceSummary", "DeviceSummaryLookup", "DeviceSummaryPage"]
