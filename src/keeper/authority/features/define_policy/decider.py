"""The decision: what defining a policy produces.

Pure. No awaits, no ports, no clock. `now` and `new_id` arrive as
parameters precisely so this function has nothing to invent.
"""

from datetime import datetime
from uuid import UUID

from keeper.authority.aggregates.policy import (
    Policy,
    PolicyAlreadyExistsError,
    PolicyDefined,
    reject_an_ungovernable_policy,
    reject_the_system_principal,
)
from keeper.authority.features.define_policy.command import DefinePolicy


def decide(
    state: Policy | None,
    command: DefinePolicy,
    *,
    now: datetime,
    new_id: UUID,
) -> list[PolicyDefined]:
    """Decide the events produced by defining a policy.

    Invariants:
      - State must be None, or the id already has a history
        -> PolicyAlreadyExistsError
      - No permission may name the system principal as its grantee
        -> SystemPrincipalCannotBeGrantedError
      - Someone must be permitted to change the policy afterwards
        -> PolicyWouldBeUngovernableError

    The last one is why an empty permission set is no longer accepted,
    which it was in the commit that landed this slice. Nothing could
    change a policy then, so a policy permitting nothing was merely
    inert and a deployment switched rulebooks by pointing at a different
    id. Granting exists now, so the same empty policy is a rulebook that
    permits nothing AND permits nobody to fix that, and the command
    which would put it right is the one nobody may issue.

    The governance check runs against the permissions being written
    rather than against anything remembered, so a policy is born able to
    be changed or is not born at all. Revoking asks the same helper the
    same question about the set it would leave behind, which is what
    keeps the two ends of a policy's life from drifting on what
    governable means.
    """
    if state is not None:
        raise PolicyAlreadyExistsError(state.id)
    reject_the_system_principal(command.permissions)
    reject_an_ungovernable_policy(command.permissions)
    return [
        PolicyDefined(
            policy_id=new_id,
            permissions=command.permissions,
            occurred_at=now,
        )
    ]


__all__ = ["decide"]
