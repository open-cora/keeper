"""The decision that granting a permission produces.

The two worth reading are the duplicate refusal and the absent
governance check. Both are choices rather than consequences, and neither
is visible from the code without knowing what was decided against.
"""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from keeper.authority.aggregates.policy import (
    Permission,
    Policy,
    PolicyCannotGrantPermissionError,
    PolicyNotFoundError,
    PolicyPermissionGranted,
    SystemPrincipalCannotBeGrantedError,
)
from keeper.authority.features.grant_permission import GrantPolicyPermission, decide
from keeper.shared.reserved_ids import SYSTEM_PRINCIPAL_ID

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 9, 17, 12, 0, tzinfo=UTC)


def _policy(*permissions: Permission) -> Policy:
    return Policy(id=uuid4(), permissions=frozenset(permissions))


def test_granting_a_new_permission_emits_the_pair_that_was_added() -> None:
    policy = _policy(Permission(principal_id=uuid4(), command_name="GrantPolicyPermission"))
    added = Permission(principal_id=uuid4(), command_name="RegisterActor")

    events = decide(policy, GrantPolicyPermission(policy.id, added), now=_NOW)

    assert events == [
        PolicyPermissionGranted(policy_id=policy.id, permission=added, occurred_at=_NOW)
    ]


def test_the_event_carries_one_pair_rather_than_the_resulting_set() -> None:
    """What happened, not what is now true.

    A snapshot of the whole set would make two operators granting
    different permissions overwrite each other, since each would write
    the set as it saw it.
    """
    existing = Permission(principal_id=uuid4(), command_name="GrantPolicyPermission")
    added = Permission(principal_id=uuid4(), command_name="RegisterActor")

    (event,) = decide(_policy(existing), GrantPolicyPermission(uuid4(), added), now=_NOW)

    assert event.permission == added
    assert not hasattr(event, "permissions")


def test_granting_under_a_policy_that_does_not_exist_is_refused() -> None:
    added = Permission(principal_id=uuid4(), command_name="RegisterActor")
    policy_id = uuid4()

    with pytest.raises(PolicyNotFoundError):
        decide(None, GrantPolicyPermission(policy_id, added), now=_NOW)


def test_granting_a_permission_the_policy_already_holds_is_refused() -> None:
    """A set would absorb it silently, which is the reason to refuse.

    Two operators granting what each believes to be a new permission
    should not both be told they granted it. One is reading a stale
    rulebook and needs to know.
    """
    held = Permission(principal_id=uuid4(), command_name="RegisterActor")
    policy = _policy(held, Permission(principal_id=uuid4(), command_name="GrantPolicyPermission"))

    with pytest.raises(PolicyCannotGrantPermissionError, match="RegisterActor"):
        decide(policy, GrantPolicyPermission(policy.id, held), now=_NOW)


def test_granting_the_same_command_to_a_different_principal_is_allowed() -> None:
    """The pair is the unit, so a shared command name is not a duplicate."""
    policy = _policy(Permission(principal_id=uuid4(), command_name="RegisterActor"))
    someone_else = Permission(principal_id=uuid4(), command_name="RegisterActor")

    (event,) = decide(policy, GrantPolicyPermission(policy.id, someone_else), now=_NOW)

    assert event.permission == someone_else


def test_granting_to_the_system_principal_is_refused() -> None:
    policy = _policy(Permission(principal_id=uuid4(), command_name="GrantPolicyPermission"))
    shortcut = Permission(principal_id=SYSTEM_PRINCIPAL_ID, command_name="RegisterActor")

    with pytest.raises(SystemPrincipalCannotBeGrantedError):
        decide(policy, GrantPolicyPermission(policy.id, shortcut), now=_NOW)


def test_granting_never_refuses_on_governance_grounds() -> None:
    """Adding cannot remove a way to change the policy.

    Asserted rather than left implicit, because the governance guard is
    conspicuous by its absence here and a later reader may take that for
    an oversight. Granting into a policy that nobody can change is fine:
    it is no worse than it was, and the guard belongs on removal.
    """
    frozen = _policy(Permission(principal_id=uuid4(), command_name="RegisterActor"))
    added = Permission(principal_id=uuid4(), command_name="GetActor")

    (event,) = decide(frozen, GrantPolicyPermission(frozen.id, added), now=_NOW)

    assert event.permission == added
