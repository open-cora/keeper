"""The intent: record that this device came back from a fault."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from keeper.shared.instant import normalize_occurred_at


@dataclass(frozen=True)
class RecoverDevice:
    """Record that this device came back from a fault.

    Recover, not restore. Restoring is something somebody does, and
    usually nobody did: the condition ended, the camera cooled, the
    alarm cleared. The pair a reader already knows is fault and
    recovery.

    Carries no more than its partner does, for the same reasons.

    `occurred_at` is when it came back, as the caller reports it, and a
    caller who omits it gets the moment the report arrived.
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


__all__ = ["RecoverDevice"]
