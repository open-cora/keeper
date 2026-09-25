"""The decision: what granting a permission produces.

Pure. Update-style, so `now` arrives as a parameter and there is no
`new_id`: the policy already exists and the event names it.
"""

from datetime import datetime

from keeper.authority.aggregates.policy import (
    Policy,
    PolicyCannotGrantPermissionError,
    PolicyNotFoundError,
    PolicyPermissionGranted,
    reject_the_system_principal,
)
from keeper.authority.features.grant_permission.command import GrantPolicyPermission


def decide(
    state: Policy | None,
    command: GrantPolicyPermission,
    *,
    now: datetime,
) -> list[PolicyPermissionGranted]:
    """Decide the events produced by granting a permission.

    Invariants:
      - The policy must exist
        -> PolicyNotFoundError
      - The permission may not name the system principal as its grantee
        -> SystemPrincipalCannotBeGrantedError
      - The permission must not already be held
        -> PolicyCannotGrantPermissionError

    There is no governance check here, and its absence is the point.
    Granting only ever adds, so no grant can leave a policy with fewer
    ways to be changed than it had. The guard belongs on the command
    that removes something, and lands with it.

    The duplicate refusal is a choice rather than a consequence. A set
    absorbs a repeated member silently, which would report success to an
    operator acting on a rulebook they had already changed.
    """
    if state is None:
        raise PolicyNotFoundError(command.policy_id)
    reject_the_system_principal([command.permission])
    if command.permission in state.permissions:
        raise PolicyCannotGrantPermissionError(
            command.permission.principal_id, command.permission.command_name
        )
    return [
        PolicyPermissionGranted(
            policy_id=command.policy_id,
            permission=command.permission,
            occurred_at=now,
        )
    ]


__all__ = ["decide"]
