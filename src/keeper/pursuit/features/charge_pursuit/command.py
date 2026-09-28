"""The intent: record what this pursuit has consumed somewhere else."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from keeper.pursuit.aggregates.pursuit import BudgetDimension
from keeper.shared.instant import normalize_occurred_at


@dataclass(frozen=True)
class ChargePursuit:
    """Add this much consumption, in this dimension, to what the pursuit has spent.

    The one command in this context that describes rather than makes. Beam
    seconds are measured by whatever measures beam and tokens are counted
    by a thinker; both happened somewhere else, at a moment this system was
    not present for, and the caller was. So `occurred_at` is the caller's,
    which is R8 landing on the describing side beside `report_step`.

    Charges add rather than replace. A reporter sending what one round
    spent does not have to read the pursuit first to find out what every
    round before it spent, which is the difference between a thinker able
    to charge its own tokens and one that has to fetch a record to do it.

    That also makes a redelivered charge wrong rather than harmless, which
    is why this is the one surface in this context with a retry key that
    does anything.

    Only a dimension nothing here can measure may be named. Rounds,
    executions and wall seconds are computed from the pursuit's own history
    and the clock, so a charge against one would be counted twice, and the
    decider refuses it.
    """

    pursuit_id: UUID
    dimension: BudgetDimension
    amount: int
    occurred_at: datetime | None = None

    def __post_init__(self) -> None:
        """Refuse a naive timestamp and store the UTC form of an aware one.

        Frozen, so the normalised value goes back through
        `object.__setattr__`, the way the shared identifier does it.
        """
        if self.occurred_at is not None:
            object.__setattr__(self, "occurred_at", normalize_occurred_at(self.occurred_at))


__all__ = ["ChargePursuit"]
