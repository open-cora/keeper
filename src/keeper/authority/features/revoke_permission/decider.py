"""The decision: what revoking a permission produces.

Pure. Update-style, so `now` arrives as a parameter and there is no
`new_id`: the policy already exists and the event names it.
"""

from datetime import datetime

from keeper.authority.aggregates.policy import (
    Policy,
    PolicyCannotRevokePermissionError,
    PolicyNotFoundError,
    PolicyPermissionRevoked,
    reject_an_ungovernable_policy,
)
from keeper.authority.features.revoke_permission.command import RevokePolicyPermission


def decide(
    state: Policy | None,
    command: RevokePolicyPermission,
    *,
    now: datetime,
) -> list[PolicyPermissionRevoked]:
    """Decide the events produced by revoking a permission.

    Invariants:
      - The policy must exist
        -> PolicyNotFoundError
      - The permission must currently be held
        -> PolicyCannotRevokePermissionError
      - What is left must still be changeable by somebody
        -> PolicyWouldBeUngovernableError

    The governance guard is the reason this slice carries one and
    granting does not. Removal is the only direction that can take a
    power away, and the power it must never take away is the one that
    puts everything else back. The check runs against the set the policy
    WOULD hold, not the one it holds, so it refuses the last removal
    rather than reporting on the state before it.

    The system principal is deliberately not screened here. It cannot
    hold a permission, because both writing paths refuse to grant it
    one, so a revoke naming it is already answered by the not-held
    refusal and answered correctly. Screening it as well would refuse a
    revoke on grant-side grounds, and would make a permission the log
    somehow holds unremovable, which is the wrong way for a guard to
    fail.
    """
    if state is None:
        raise PolicyNotFoundError(command.policy_id)
    if command.permission not in state.permissions:
        raise PolicyCannotRevokePermissionError(
            command.permission.principal_id, command.permission.command_name
        )
    reject_an_ungovernable_policy(state.permissions - {command.permission})
    return [
        PolicyPermissionRevoked(
            policy_id=command.policy_id,
            permission=command.permission,
            occurred_at=now,
        )
    ]


__all__ = ["decide"]
