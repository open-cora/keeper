"""Replay Device events to reconstruct current state.

`evolve` applies one event. `fold` walks a whole stream from the empty
state, which is what the read path calls after loading rows.

Both are pure and total: the same events in the same order always give
the same state, on any machine, years apart. That is the property the
whole approach rests on, and it is why nothing here reads a clock, a
config value or a database.

The status is computed here and stored nowhere. Each transition arm sets
it from the event that arrived, so the value can never disagree with the
history behind it. Note that the status is the only thing the three
transitions change: a fault does not alter the device's address or its
label, so `replace` touches one field and the rest carry through.

The wildcard arm calls `assert_never`, so adding an event class to the
union without handling it here is a type error rather than a state that
silently comes back as None.
"""

from collections.abc import Sequence
from dataclasses import replace
from typing import assert_never

from keeper.equipment.aggregates.device.events import (
    DeviceEvent,
    DeviceFaulted,
    DeviceRecovered,
    DeviceRegistered,
    DeviceRetired,
)
from keeper.equipment.aggregates.device.state import Device, DeviceName, DeviceStatus
from keeper.infrastructure.slices.evolver import require_state
from keeper.shared.identifier import Identifier


def evolve(state: Device | None, event: DeviceEvent) -> Device:
    """Apply one event to the state before it.

    The genesis arm builds the device and ignores the prior state, which
    must be None. The other three require one, because nothing can be
    reported about a device that was never registered.

    The genesis re-validates as it rebuilds: the reference and the label
    go back through their value objects rather than being copied as the
    strings the payload holds. That is what docs/reference/modeling.md
    asks for, and it means a payload that could not be constructed today
    fails on read rather than becoming state nothing checked.
    """
    match event:
        case DeviceRegistered(
            device_id=device_id,
            external_ref_scheme=scheme,
            external_ref_value=value,
            device_name=device_name,
        ):
            _ = state
            return Device(
                id=device_id,
                external_ref=Identifier(scheme=scheme, value=value),
                name=DeviceName(device_name),
                status=DeviceStatus.AVAILABLE,
            )
        case DeviceFaulted():
            return replace(require_state(state, "DeviceFaulted"), status=DeviceStatus.FAULTED)
        case DeviceRecovered():
            return replace(require_state(state, "DeviceRecovered"), status=DeviceStatus.AVAILABLE)
        case DeviceRetired():
            return replace(require_state(state, "DeviceRetired"), status=DeviceStatus.RETIRED)
        case _:
            assert_never(event)


def fold(events: Sequence[DeviceEvent]) -> Device | None:
    """Replay a stream from the empty state. None means no events at all.

    Takes a `Sequence` rather than a `list` so a caller holding a list of
    one concrete event type can pass it without a cast, which is most
    callers in tests.
    """
    state: Device | None = None
    for event in events:
        state = evolve(state, event)
    return state


__all__ = ["evolve", "fold"]
