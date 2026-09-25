"""The decision: what registering a device produces.

Pure. No awaits, no ports, no clock. `now` and `new_id` arrive as
parameters precisely so this function has nothing to fetch and nothing
to invent.

There is no context module beside this one. This context reaches into no
sibling at all: a device is not tied to a run, and nothing about
enrolling one needs to know what was running at the time. So there is no
cross-context door to hold open and nothing for a context holder to
carry.
"""

from datetime import datetime
from uuid import UUID

from keeper.equipment.aggregates.device import (
    Device,
    DeviceAlreadyExistsError,
    DeviceRegistered,
)
from keeper.equipment.features.register_device.command import RegisterDevice


def decide(
    state: Device | None,
    command: RegisterDevice,
    *,
    now: datetime,
    new_id: UUID,
) -> list[DeviceRegistered]:
    """Decide the events produced by registering a device.

    Invariants:
      - State must be None, or the id already has a history
        -> DeviceAlreadyExistsError

    One invariant, which is the honest count. This context holds a
    reference to something it cannot reach, so there is nothing here to
    check it against: no way to ask whether the address resolves, no way
    to ask whether anything is listening at it, and no way to tell a
    motor from a typo. What can be refused is refused earlier, by
    `Identifier` and `DeviceName` when they are built at the edge.

    What is NOT checked is whether some other device already names this
    same address. Nothing here can see another stream, so registering
    one motor twice makes two records and nothing notices. That gap is
    real and it matters more here than it does for a dataset, because a
    reporter resolving an address is choosing which device to fault and
    two matches leave it choosing. Closing it needs one of the
    cross-stream patterns in docs/reference/patterns.md rather than a
    rule in this function, and the summary port is written so a caller
    can at least SEE both.
    """
    if state is not None:
        raise DeviceAlreadyExistsError(state.id)
    return [
        DeviceRegistered(
            device_id=new_id,
            external_ref_scheme=command.external_ref.scheme,
            external_ref_value=command.external_ref.value,
            device_name=command.name.value,
            occurred_at=now,
        )
    ]


__all__ = ["decide"]
