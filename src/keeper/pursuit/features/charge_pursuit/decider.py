"""The decision: what charging a pursuit produces.

Pure. No awaits, no ports, no clock. `now` arrives as a parameter and is
the fallback for a caller that named no moment of its own.
"""

from datetime import datetime

from keeper.pursuit.aggregates.pursuit import (
    InvalidPursuitChargeError,
    Pursuit,
    PursuitCharged,
)
from keeper.pursuit.features.charge_pursuit.command import ChargePursuit


def decide(
    state: Pursuit,
    command: ChargePursuit,
    *,
    now: datetime,
) -> list[PursuitCharged]:
    """Decide the events produced by charging a pursuit.

    Invariants:
      - The amount must be positive -> InvalidPursuitChargeError
      - The dimension must be one this system cannot measure for itself
        -> InvalidPursuitChargeError
      - The dimension must be one this pursuit was bounded in
        -> InvalidPursuitChargeError

    The last of those is the arguable one. A charge against a dimension
    with no limit could be recorded harmlessly, since nothing would ever
    read it, and that is the argument for refusing: a number nothing reads,
    accumulating on a record nobody can edit, is far more likely to be a
    caller naming the wrong pursuit than a deliberate note.

    **A stopped pursuit is charged like any other, and that is deliberate.**
    What this records happened out in the world, so refusing it would make
    the record disagree with what was consumed. Beam seconds from the run
    that was in flight when somebody withdrew the pursuit are real seconds,
    and the withdrawal is exactly when they arrive. This is what a
    describing command means: the world is the authority, and the record is
    late rather than in charge.

    The amount going negative is refused rather than allowed as a
    correction. A correction that silently reduces what a loop has spent is
    a way to extend a budget without anybody authorizing more, and the
    honest way to give a pursuit more room is to start another.
    """
    if command.amount <= 0:
        raise InvalidPursuitChargeError(
            command.pursuit_id, f"the amount is {command.amount} and must be positive"
        )
    if not command.dimension.is_reported:
        raise InvalidPursuitChargeError(
            command.pursuit_id,
            f"{command.dimension} is counted from this record and cannot be reported into it",
        )
    if command.dimension not in state.budget.limits:
        raise InvalidPursuitChargeError(
            command.pursuit_id, f"it was never bounded in {command.dimension}"
        )
    return [
        PursuitCharged(
            pursuit_id=command.pursuit_id,
            dimension=command.dimension.value,
            amount=command.amount,
            occurred_at=command.occurred_at or now,
        )
    ]


__all__ = ["decide"]
