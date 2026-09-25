"""The question: which devices, newest first, and where do I carry on from?

The query a fold cannot answer. `GetDevice` names the device it wants;
this one is asking which device to name, and the only way to answer that
from an event log is to have kept a summary of it as the events arrived.

Four parameters and they are three kinds of thing. Two filters say which
devices. The limit says how many of them. The cursor says where the last
page stopped.
"""

from dataclasses import dataclass

from keeper.equipment.aggregates.device.state import DeviceStatus, InvalidDeviceFilterError
from keeper.shared.identifier import Identifier

DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 100
"""How many devices one page carries, by default and at most.

The same two numbers the sibling contexts use, and deliberately the same
rather than tuned: a page size is a property of the surface rather than
of what is on the page, and a caller paging four lists should not have
to learn four conventions.
"""


@dataclass(frozen=True)
class ListDevices:
    """Read a page of devices, newest first.

    `external_ref` is the address a control system publishes a device
    at, and it is the reason an adapter can use this context at all. A
    reporter watching a beamline holds an address and nothing else,
    because ids are minted here, so resolving one to an id is its first
    call and every fault it reports depends on it.

    Not guaranteed to match at most one device. Nothing stops two
    records of one address, so this answers with however many there are
    and lets the caller see the duplicate rather than hiding it behind a
    lookup that can only return one. That matters more here than it does
    for a run: a caller resolving a run is reading, and a caller
    resolving a device is about to write to whatever comes back.

    `status` narrows to one disposition, which is the operator's
    question rather than the adapter's. The two filters combine.
    """

    external_ref: Identifier | None = None
    status: DeviceStatus | None = None
    limit: int = DEFAULT_PAGE_SIZE
    cursor: str | None = None

    @classmethod
    def with_external_ref(
        cls,
        *,
        scheme: str | None,
        value: str | None,
        status: DeviceStatus | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
        cursor: str | None = None,
    ) -> "ListDevices":
        """Build a query from the two halves a surface receives separately.

        Both surfaces take the scheme and the value as two parameters,
        because `Identifier` puts no pattern on a scheme and a single
        `scheme:value` string could not be split with any confidence.
        That makes "exactly one half arrived" a shape both of them can
        produce, so the refusal lives here rather than twice at the
        edges.

        A `classmethod` rather than a check in `__post_init__`, because
        the field is one optional `Identifier` and by the time it exists
        the halves have already been paired. This is the only place that
        pairing happens.
        """
        if (scheme is None) != (value is None):
            raise InvalidDeviceFilterError(scheme, value)
        external_ref = (
            Identifier(scheme=scheme, value=value)
            if scheme is not None and value is not None
            else None
        )
        return cls(external_ref=external_ref, status=status, limit=limit, cursor=cursor)


__all__ = ["DEFAULT_PAGE_SIZE", "MAX_PAGE_SIZE", "ListDevices"]
