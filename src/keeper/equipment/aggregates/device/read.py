"""Load a Device by replaying its stream.

Two loaders, and the difference between them is the version. A handler
about to append to a stream that already has rows needs the version it
folded from, so that two reporters faulting the same device at once
produce one append and one conflict rather than two rows saying the same
thing. A reader needs no such thing and gets the shorter function.

Both are here from the first landing, the way Counsel's are, because
this aggregate has three commands beyond its genesis. Custody has only
the shorter one, because nothing appends to a dataset after its genesis.

There is no devices table: the answer is recomputed from history on
every call. That is the right trade for reading one device by id, where
a stream is a handful of rows. It is the wrong trade for listing the
faulted ones, which cannot name a stream and so cannot fold one, and
which needs a maintained summary table instead. That belongs in its own
module and is `summary.py`.

Lives with the aggregate rather than with a slice because it reads the
aggregate's whole stream, whatever command happened to write each row.
"""

from uuid import UUID

from keeper.equipment.aggregates.device.events import from_stored
from keeper.equipment.aggregates.device.evolver import fold
from keeper.equipment.aggregates.device.state import Device
from keeper.infrastructure.ports.event_store import EventStore

DEVICE_STREAM_TYPE = "Device"
"""The stream type every Device event is stored under.

Half of the `(stream_type, event_type)` routing key. Declared as a
constant because the writing side and this reading side must agree on it
and they are in different files.
"""


async def load_device(event_store: EventStore, device_id: UUID) -> Device | None:
    """Return the device's current state, or None if the stream is empty.

    An empty stream means no such device was ever registered. The caller
    decides what that means on its own surface: a 404 over HTTP, an error
    result over MCP.
    """
    stored, _version = await event_store.load(DEVICE_STREAM_TYPE, device_id)
    return fold([from_stored(row) for row in stored])


async def load_device_with_version(
    event_store: EventStore, device_id: UUID
) -> tuple[Device | None, int]:
    """Return the device's state and the version it was folded from.

    The version is what a writing handler passes back as
    `expected_version`, so that two reporters acting on one device at
    once produce one append and one `ConcurrencyError`. Without it the
    second append would land a transition the decider had no chance to
    refuse, because it decided against state that was already stale.
    """
    stored, version = await event_store.load(DEVICE_STREAM_TYPE, device_id)
    return fold([from_stored(row) for row in stored]), version


__all__ = ["DEVICE_STREAM_TYPE", "load_device", "load_device_with_version"]
