"""Events the Device aggregate emits, and the union its evolver dispatches on.

Events live with the aggregate rather than with the slice that emits
them, because they are facts about the aggregate's history. A slice
decides when one happens; the history is not the slice's to own.

## Four events, and the family has a shape

    DeviceRegistered   this system enrolled it
    DeviceFaulted      something out there went wrong with it
    DeviceRecovered    it came back
    DeviceRetired      this system stopped counting it

Two administrative bookends with two reported transitions between them,
and that shape is what decides which commands may carry a time. Every
event below carries an `occurred_at`, because the envelope needs one;
what differs is where it comes from. For the bookends it is this
system's clock, because the act is the call. For the middle pair it may
be the caller's, because the fault happened at a beamline at a moment
nothing here was present for. R8 in docs/reference/naming.md draws that
line, and the commands are where it is visible.

The reference travels as two flat strings and is rebuilt into a pair by
the fold, because events carry primitives and that pair is a value
object. The label travels as a bare string for the same reason.

`device_name`, not `name`. Qualified for the reason `PlanDefined` gives
next door: the personal-data check reads field names and cannot tell a
piece of hardware's label from a person's name, and an unqualified
`name` on an append-only row is the exact shape that rule exists to
stop. The qualifier earns more here than it does there, because the one
value this field must never hold is a control system's own description
field, which is where an operator's free text lives.

## Why the three transitions carry nothing but a time

No severity, no reason, no reporter. The severity is left off because a
fault is the reporter's judgement and a number on the record invites a
later reader to re-derive that judgement badly; the module docstring on
`state.py` has the argument. A reason is left off because free text from
a control system is where a person's name arrives, which is the call
`ActorDeactivated` and a run's endings already make. Who reported it is
on the envelope, where every other command's principal is.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, assert_never
from uuid import UUID

from keeper.infrastructure.ports.event_store import StoredEvent
from keeper.infrastructure.slices.payload import deserialize_or_raise


@dataclass(frozen=True)
class DeviceRegistered:
    """A piece of hardware was enrolled in this system's record.

    Registered rather than defined, and the glossary's read-aloud test
    settles it: "define a device" sounds like inventing hardware, which
    this system did not do and could not. The motor is at the beamline
    whether or not anything here has heard of it, and this event is the
    hearing.

    It is the second `register_*` in this tree to describe a thing that
    exists outside, and it goes the OTHER way from the first on time.
    `register_dataset` takes a caller's `occurred_at` because the data
    was written somewhere at a knowable moment. Enrolling a device has
    no such moment: when the hardware was installed is not something any
    adapter can supply, and the only act this system can date is its own
    enrolling. So the command takes no time and this field is the clock,
    which puts it beside `register_actor`.
    """

    device_id: UUID
    external_ref_scheme: str
    external_ref_value: str
    device_name: str
    occurred_at: datetime


@dataclass(frozen=True)
class DeviceFaulted:
    """Something was reported wrong with the device.

    The one event on this stream that is a claim about the world. What
    a control system publishes is an alarm severity, and turning that
    into a fault is the reporter's judgement, the same judgement it
    makes when it picks one of a run's three terminals.

    Carries a caller's `occurred_at`, because the fault happened out
    there. A reporter genuinely has the moment to supply: an alarm
    arrives on a timestamped update.
    """

    device_id: UUID
    occurred_at: datetime


@dataclass(frozen=True)
class DeviceRecovered:
    """The device came back from a fault.

    Recovered rather than restored. Restoring is something somebody
    does, and usually nobody did: the condition ended. The pair a
    reader already knows is fault and recovery.

    Carries a caller's `occurred_at`, for the same reason its partner
    does.
    """

    device_id: UUID
    occurred_at: datetime


@dataclass(frozen=True)
class DeviceRetired:
    """A device left this system's active register.

    Retired rather than withdrawn, on two counts. Withdrawn is spoken
    for: a proposal is what gets withdrawn in this tree, by the party
    that made it, and the glossary defines each term once. And retiring
    is the ordinary word for taking a thing out of an active register,
    which is exactly what this is.

    What it does NOT claim is that the hardware was removed from the
    beamline. That is a different fact, at a different moment, which
    this system was not present for and does not model. This record
    makes its own fact, so the command takes no time and this field is
    the clock.
    """

    device_id: UUID
    occurred_at: datetime


DeviceEvent = DeviceRegistered | DeviceFaulted | DeviceRecovered | DeviceRetired
"""Every event that can appear on a Device stream.

A new member is a new class added here and to this union, never a field
bolted onto an event already in the log. Adding one without teaching the
evolver about it is a type error, because the wildcard arm there calls
`assert_never`.
"""


def to_payload(event: DeviceEvent) -> dict[str, Any]:
    """Render an event as the primitives that get stored."""
    match event:
        case DeviceRegistered():
            return {
                "device_id": str(event.device_id),
                "external_ref_scheme": event.external_ref_scheme,
                "external_ref_value": event.external_ref_value,
                "device_name": event.device_name,
                "occurred_at": event.occurred_at.isoformat(),
            }
        case DeviceFaulted() | DeviceRecovered() | DeviceRetired():
            return {
                "device_id": str(event.device_id),
                "occurred_at": event.occurred_at.isoformat(),
            }
        case _:
            assert_never(event)


def from_stored(stored: StoredEvent) -> DeviceEvent:
    """Rebuild an event from its stored row.

    `extra` carries `ValueError` because the constructors below raise it
    on malformed input: a string that is not a UUID, and one that is not
    a timestamp. Without it those escape as themselves, naming the field
    rather than the event.

    The three transitions share an arm shape but not an arm, because
    each has to name its own class to build it.
    """
    payload = stored.payload
    match stored.event_type:
        case "DeviceRegistered":
            return deserialize_or_raise(
                "DeviceRegistered",
                lambda: DeviceRegistered(
                    device_id=UUID(payload["device_id"]),
                    external_ref_scheme=payload["external_ref_scheme"],
                    external_ref_value=payload["external_ref_value"],
                    device_name=payload["device_name"],
                    occurred_at=datetime.fromisoformat(payload["occurred_at"]),
                ),
                extra=(ValueError,),
            )
        case "DeviceFaulted":
            return deserialize_or_raise(
                "DeviceFaulted",
                lambda: DeviceFaulted(
                    device_id=UUID(payload["device_id"]),
                    occurred_at=datetime.fromisoformat(payload["occurred_at"]),
                ),
                extra=(ValueError,),
            )
        case "DeviceRecovered":
            return deserialize_or_raise(
                "DeviceRecovered",
                lambda: DeviceRecovered(
                    device_id=UUID(payload["device_id"]),
                    occurred_at=datetime.fromisoformat(payload["occurred_at"]),
                ),
                extra=(ValueError,),
            )
        case "DeviceRetired":
            return deserialize_or_raise(
                "DeviceRetired",
                lambda: DeviceRetired(
                    device_id=UUID(payload["device_id"]),
                    occurred_at=datetime.fromisoformat(payload["occurred_at"]),
                ),
                extra=(ValueError,),
            )
        case unknown:
            msg = f"Unknown Device event_type: {unknown!r}"
            raise ValueError(msg)


__all__ = [
    "DeviceEvent",
    "DeviceFaulted",
    "DeviceRecovered",
    "DeviceRegistered",
    "DeviceRetired",
    "from_stored",
    "to_payload",
]
