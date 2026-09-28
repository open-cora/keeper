"""The decision: what starting a pursuit produces.

Pure. No awaits, no ports, no clock. `now`, `new_id` and `actor_id` arrive
as parameters precisely so this function has nothing to fetch and nothing
to invent.

There is no context module beside this one. Authorizing a loop is a
decision about this aggregate alone: nothing is loaded, nothing is
cross-checked, and there is no sibling whose state could make this
authorization wrong. The checks that matter run at the edge, where the
value objects are built, and on the scopes here.
"""

from datetime import datetime
from uuid import UUID

from keeper.pursuit.aggregates.pursuit import (
    Pursuit,
    PursuitAlreadyExistsError,
    PursuitStarted,
    validate_scopes,
)
from keeper.pursuit.features.start_pursuit.command import StartPursuit


def decide(
    state: Pursuit | None,
    command: StartPursuit,
    *,
    actor_id: UUID,
    now: datetime,
    new_id: UUID,
) -> list[PursuitStarted]:
    """Decide the events produced by starting a pursuit.

    Invariants:
      - State must be None, or the id already has a history
        -> PursuitAlreadyExistsError
      - The scopes must be non-empty, individually non-empty, and within
        their bounds -> InvalidPursuitScopesError

    What is NOT checked is whether the beamline exists, whether the scopes
    name devices this system has heard of, or whether the principal has any
    standing at that beamline beyond being allowed to issue this command at
    all. None of the three is checkable here and two of them are not
    checkable anywhere: Equipment holds devices by the address a control
    system publishes them at and reaches into no sibling, and nothing in
    this tree holds beamlines at all.

    That gap is worth naming rather than papering over. A pursuit can be
    authorized over a scope nothing will ever match, and what happens then
    is that it dispatches work no conductor takes. It cannot be authorized
    over a scope somebody forgot to write down, which is the direction that
    would matter.
    """
    if state is not None:
        raise PursuitAlreadyExistsError(state.id)
    return [
        PursuitStarted(
            pursuit_id=new_id,
            actor_id=actor_id,
            goal=command.goal.value,
            beamline=command.beamline.value,
            scopes=validate_scopes(command.scopes),
            budget={dimension.value: limit for dimension, limit in command.budget.limits.items()},
            occurred_at=now,
        )
    ]


__all__ = ["decide"]
