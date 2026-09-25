"""The intent: record that something has taken a dispatched execution up."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from keeper.shared.instant import normalize_occurred_at


@dataclass(frozen=True)
class ClaimExecution:
    """Say that the caller is driving the execution with this id.

    Claim, and not start. Starting would say a step has run, and nothing
    has: this says only that a dispatch sitting unread has been picked
    up. The first step report is what moves the execution to running, and a
    driver that never sends one leaves a claimed execution that never moved,
    which is a fact worth being able to see.

    No field naming the claimant. The envelope carries the principal that
    issued the command, and a deployment runs one service account per
    beamline, so a field here would be a second copy that could disagree.

    `occurred_at` is when the execution was taken up, as the caller reports
    it, and it is optional: a caller who omits it gets the moment the
    report arrived. Accepted for the reason the step reports accept one,
    because a driver at a beamline picks work up on its own clock.
    """

    execution_id: UUID
    occurred_at: datetime | None = None

    def __post_init__(self) -> None:
        """Refuse a naive timestamp and store the UTC form of an aware one.

        Frozen, so the normalised value goes back through
        `object.__setattr__`, the way the shared identifier does it.
        """
        if self.occurred_at is not None:
            object.__setattr__(self, "occurred_at", normalize_occurred_at(self.occurred_at))


__all__ = ["ClaimExecution"]
