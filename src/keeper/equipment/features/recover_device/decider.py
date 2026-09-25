"""The decision: what recovering a device produces.

Update-style, so the state comes in already folded and `new_id` is
absent: this command names its stream rather than creating one.

Pure. No awaits, no ports, no clock.
"""

from datetime import datetime

from keeper.equipment.aggregates.device import (
    Device,
    DeviceCannotBeRecoveredError,
    DeviceNotFoundError,
    DeviceRecovered,
    DeviceStatus,
)
from keeper.equipment.features.recover_device.command import RecoverDevice


def decide(
    state: Device | None,
    command: RecoverDevice,
    *,
    now: datetime,
) -> list[DeviceRecovered]:
    """Decide the events produced by recovering a device.

    Invariants:
      - State must not be None, or no such device was registered
        -> DeviceNotFoundError
      - The device must be faulted
        -> DeviceCannotBeRecoveredError

    The mirror of its partner, and the two are not equally likely to be
    hit. A duplicate fault is usually a redelivery. A recovery against
    an AVAILABLE device usually means the reporter never delivered the
    fault, which is the ordinary failure here rather than the exotic
    one: a fault reaches only whoever was subscribed at the time, and a
    reporter that restarted was not.

    Refusing it is still right, and the reason is worth stating because
    the alternative looks kinder. Absorbing an unmatched recovery would
    let a stream carry a recovery for a fault it never recorded, and a
    later reader counting outages would find their ends without their
    beginnings. The status on the error is what tells the caller which
    case it is in, and the honest repair for a missed fault is to
    report it.
    """
    if state is None:
        raise DeviceNotFoundError(command.device_id)
    if state.status is not DeviceStatus.FAULTED:
        raise DeviceCannotBeRecoveredError(state.id, state.status)
    return [DeviceRecovered(device_id=command.device_id, occurred_at=now)]


__all__ = ["decide"]
