"""The decision: what retiring a device produces.

Update-style, so the state comes in already folded and `new_id` is
absent: this command names its stream rather than creating one.

Pure. No awaits, no ports, no clock.
"""

from datetime import datetime

from keeper.equipment.aggregates.device import (
    Device,
    DeviceCannotBeRetiredError,
    DeviceNotFoundError,
    DeviceRetired,
)
from keeper.equipment.features.retire_device.command import RetireDevice


def decide(
    state: Device | None,
    command: RetireDevice,
    *,
    now: datetime,
) -> list[DeviceRetired]:
    """Decide the events produced by retiring a device.

    Invariants:
      - State must not be None, or no such device was registered
        -> DeviceNotFoundError
      - The device must not already be retired
        -> DeviceCannotBeRetiredError

    One refusal, and the narrowest of the three. A faulted device may be
    retired and so may an available one; only a second retirement is
    refused, because the register has already stopped carrying it and a
    second row would not change that.

    Retiring is not deleting. The stream stays, the history stays
    readable, and a reader asking what this device did last year still
    gets an answer. What changes is that the device is no longer one the
    system counts as present.
    """
    if state is None:
        raise DeviceNotFoundError(command.device_id)
    if state.is_retired:
        raise DeviceCannotBeRetiredError(state.id, state.status)
    return [DeviceRetired(device_id=command.device_id, occurred_at=now)]


__all__ = ["decide"]
