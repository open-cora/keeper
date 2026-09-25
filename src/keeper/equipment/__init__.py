"""Equipment: what hardware this system knows about, and what state it is in.

One aggregate, the Device, and six operations on it. A device is one
piece of hardware this system holds a record of: where its control
system publishes it, a label for it, and what it was last reported doing.

## What identifies a device

The address its control system publishes it at, and nothing else. A
control library's name for a device is assigned in whatever process
built it, so two startup profiles name one motor differently and both
are equally correct. The facility's own description field is served
empty and any client can write it. A spike measured both
before this context was written, and the external reference is what came
out of it.

## What it will not claim

That a device works. Available means no fault has been reported and none
stands, which is the same caveat a run's Running carries and is weaker
here for three separate measured reasons: a fault reaches only whoever
was subscribed when it happened, a reporter's cached view of an alarm
outlives the device it describes, and hardware outlives the thing
driving it with no ending emitted anywhere.

That says what a reporter has to be: something that reports faults it
saw, not something whose silence means anything. A device nobody watched
reads as available forever, the way a run nobody ended reads as running.

## What it holds and what it leaves outside

The disposition, and only that. No readings, because one device
publishes tens of signals that move continuously and an append-only log
is the wrong home for them. No configuration, because a station's
configuration is mostly a named person and the easy implementation is
the one that files a badge number where nothing can edit it. No
intervals, because a fault is a point event and a span derived from two
of them rests on a clear nobody may have seen.

## What it reaches across for

Nothing, in either direction. A device is not tied to a run: it is not
registered by one, not faulted by one, and a run does not cite one.
Every other context in this tree has a door in `tach.toml`; this one has
none, and the absence is the design rather than an omission waiting to
be filled. Whether a run touched a faulted device is a question about
both, and the place to answer it is whichever context grows a reason to
ask, with a join it writes itself.
"""

from keeper.equipment.aggregates.device import Device, load_device
from keeper.equipment.errors import UnauthorizedError
from keeper.equipment.projections import register_equipment_projections
from keeper.equipment.routes import register_equipment_routes
from keeper.equipment.tools import register_equipment_tools
from keeper.equipment.wire import EquipmentHandlers, wire_equipment

__all__ = [
    "Device",
    "EquipmentHandlers",
    "UnauthorizedError",
    "load_device",
    "register_equipment_projections",
    "register_equipment_routes",
    "register_equipment_tools",
    "wire_equipment",
]
