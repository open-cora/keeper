"""The decision: what faulting a device produces.

Update-style, so the state comes in already folded and `new_id` is
absent: this command names its stream rather than creating one.

Pure. No awaits, no ports, no clock.
"""

from datetime import datetime

from keeper.equipment.aggregates.device import (
    Device,
    DeviceCannotBeFaultedError,
    DeviceFaulted,
    DeviceNotFoundError,
    DeviceStatus,
)
from keeper.equipment.features.fault_device.command import FaultDevice


def decide(
    state: Device | None,
    command: FaultDevice,
    *,
    now: datetime,
) -> list[DeviceFaulted]:
    """Decide the events produced by faulting a device.

    Invariants:
      - State must not be None, or no such device was registered
        -> DeviceNotFoundError
      - The device must be available
        -> DeviceCannotBeFaultedError

    One condition covers two refusals. A device already faulted has
    nothing to add: a second report with no recovery between them says
    what the stream already says. A retired one is no longer counted.
    The status rides on the error, so a caller learns which it hit.

    **A duplicate fault is refused rather than absorbed**, and that is
    a domain claim rather than a safety rail. Faults arrive at most
    once, delivered only to whoever was subscribed, so two reporters
    watching one device is a real configuration and a second report is
    far more likely to be a redelivery than a new fault. Recording it
    would put two indistinguishable rows on the stream and leave a
    later reader counting outages that did not happen.
    """
    if state is None:
        raise DeviceNotFoundError(command.device_id)
    if state.status is not DeviceStatus.AVAILABLE:
        raise DeviceCannotBeFaultedError(state.id, state.status)
    return [DeviceFaulted(device_id=command.device_id, occurred_at=now)]


__all__ = ["decide"]
