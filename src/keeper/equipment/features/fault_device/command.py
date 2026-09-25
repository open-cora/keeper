"""The intent: record that something was reported wrong with this device."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from keeper.shared.instant import normalize_occurred_at


@dataclass(frozen=True)
class FaultDevice:
    """Record that something was reported wrong with this device.

    The fault is the reporter's judgement, not a value copied through.
    What a control system publishes is an alarm severity, and an alarm
    is not a fault: the routine ones are routine, and a device in one is
    usually still usable. Deciding that a given severity amounts to a
    fault is the same call a reporter makes when it picks one of a run's
    three terminals.

    So nothing here carries a severity. On the record it would invite a
    later reader to re-derive the judgement from a number, which is a
    claim about hardware health this system never made.

    Nothing carries a reason either. Free text from a control system is
    where a person's name ends up, in the one table that cannot be
    edited, which is the call `ActorDeactivated` and a run's endings
    already make.

    `occurred_at` is when the fault happened, as the caller reports it,
    and a caller who omits it gets the moment the report arrived. It is
    accepted because the fault happened at a beamline at a moment
    nothing here was present for, and a reporter genuinely has the value
    to supply: an alarm arrives on a timestamped update.
    """

    device_id: UUID
    occurred_at: datetime | None = None

    def __post_init__(self) -> None:
        """Refuse a naive timestamp and store the UTC form of an aware one.

        Frozen, so the normalised value goes back through
        `object.__setattr__`, the way the shared identifier does it.
        """
        if self.occurred_at is not None:
            object.__setattr__(self, "occurred_at", normalize_occurred_at(self.occurred_at))


__all__ = ["FaultDevice"]
