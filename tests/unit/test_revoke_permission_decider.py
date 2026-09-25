"""The decision that revoking a permission produces.

The governance guard is the one worth reading, and it is the only check
in this context that asks about a state the policy does not have yet.
Whether a removal is safe cannot be read off the permission being
removed: it depends entirely on what would be left, so the guard is run
against the hypothetical set rather than the stored one.

The permission sets here are built from `GOVERNING_COMMAND_NAMES` rather
than spelled out, so a second governing command starts being exercised
the day it is added instead of the day someone remembers this file.
"""

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from keeper.authority.aggregates.policy import (
    GOVERNING_COMMAND_NAMES,
    Permission,
    Policy,
    PolicyCannotRevokePermissionError,
    PolicyNotFoundError,
    PolicyPermissionRevoked,
    PolicyWouldBeUngovernableError,
)
from keeper.authority.features.revoke_permission import RevokePolicyPermission, decide
from keeper.shared.reserved_ids import SYSTEM_PRINCIPAL_ID

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 9, 17, 12, 0, tzinfo=UTC)


def _governing(principal_id: UUID) -> frozenset[Permission]:
    """Every permission one principal needs to keep a policy changeable."""
    return frozenset(
        Permission(principal_id=principal_id, command_name=name) for name in GOVERNING_COMMAND_NAMES
    )


def test_revoking_a_held_permission_emits_the_pair_that_was_removed() -> None:
    alice, bob = uuid4(), uuid4()
    held = Permission(principal_id=bob, command_name="RegisterActor")
    policy = Policy(id=uuid4(), permissions=_governing(alice) | {held})

    events = decide(policy, RevokePolicyPermission(policy.id, held), now=_NOW)

    assert events == [
        PolicyPermissionRevoked(policy_id=policy.id, permission=held, occurred_at=_NOW)
    ]


def test_the_event_carries_one_pair_rather_than_the_survivors() -> None:
    """What happened, not what is now true.

    A snapshot of the remaining set would make two operators revoking
    different permissions overwrite each other, since each would write
    the set as it saw it.
    """
    alice, bob = uuid4(), uuid4()
    held = Permission(principal_id=bob, command_name="RegisterActor")
    policy = Policy(id=uuid4(), permissions=_governing(alice) | {held})

    (event,) = decide(policy, RevokePolicyPermission(policy.id, held), now=_NOW)

    assert event.permission == held
    assert not hasattr(event, "permissions")


def test_revoking_under_a_policy_that_does_not_exist_is_refused() -> None:
    gone = Permission(principal_id=uuid4(), command_name="RegisterActor")

    with pytest.raises(PolicyNotFoundError):
        decide(None, RevokePolicyPermission(uuid4(), gone), now=_NOW)


def test_revoking_a_permission_the_policy_does_not_hold_is_refused() -> None:
    """A set difference would absorb it, which is the reason to refuse.

    Two operators each removing what they believe to be a live
    permission should not both be told they removed it. One is reading a
    stale rulebook and needs to know.
    """
    policy = Policy(id=uuid4(), permissions=_governing(uuid4()))
    never_held = Permission(principal_id=uuid4(), command_name="RegisterActor")

    with pytest.raises(PolicyCannotRevokePermissionError, match="RegisterActor"):
        decide(policy, RevokePolicyPermission(policy.id, never_held), now=_NOW)


def test_revoking_the_same_command_from_a_different_principal_is_refused() -> None:
    """The pair is the unit, so a shared command name is not a match."""
    alice, bob = uuid4(), uuid4()
    policy = Policy(
        id=uuid4(),
        permissions=_governing(alice)
        | {Permission(principal_id=bob, command_name="RegisterActor")},
    )
    someone_else = Permission(principal_id=uuid4(), command_name="RegisterActor")

    with pytest.raises(PolicyCannotRevokePermissionError):
        decide(policy, RevokePolicyPermission(policy.id, someone_else), now=_NOW)


def test_revoking_the_last_way_to_change_the_policy_is_refused() -> None:
    """The invariant this slice exists to carry.

    The smallest legal policy is one principal holding the governing
    commands. Removing any of them leaves a rulebook whose repair
    command is the one nobody may issue, and no later request can undo
    it: the only way back is a restart with authorization switched off.
    """
    policy = Policy(id=uuid4(), permissions=_governing(uuid4()))
    last = next(iter(policy.permissions))

    with pytest.raises(PolicyWouldBeUngovernableError, match=last.command_name):
        decide(policy, RevokePolicyPermission(policy.id, last), now=_NOW)


def test_revoking_one_of_two_administrators_is_allowed() -> None:
    """The guard counts what survives, not what leaves.

    Same permission, same command, refused in the test above and
    permitted here. Only the rest of the set differs, which is what
    makes the check a question about the resulting policy rather than
    about the pair named in the command.
    """
    alice, bob = uuid4(), uuid4()
    policy = Policy(id=uuid4(), permissions=_governing(alice) | _governing(bob))
    alices = next(p for p in policy.permissions if p.principal_id == alice)

    (event,) = decide(policy, RevokePolicyPermission(policy.id, alices), now=_NOW)

    assert event.permission == alices


def test_revoking_an_ordinary_permission_from_a_sole_administrator_is_allowed() -> None:
    """Governance is about which COMMANDS survive, not which principals.

    Alice is the only party who can change this policy, and taking away
    something else she holds leaves that untouched. A guard reading
    "the last permission of the last administrator" would refuse this,
    and would be refusing an ordinary correction.
    """
    alice = uuid4()
    ordinary = Permission(principal_id=alice, command_name="RegisterActor")
    policy = Policy(id=uuid4(), permissions=_governing(alice) | {ordinary})

    (event,) = decide(policy, RevokePolicyPermission(policy.id, ordinary), now=_NOW)

    assert event.permission == ordinary


def test_revoking_never_refuses_on_system_principal_grounds() -> None:
    """The deliberate absence, asserted so it does not read as an oversight.

    Granting screens the system principal and revoking does not. It
    cannot hold a permission, because both writing paths refuse to give
    it one, so an ordinary revoke naming it is already answered by the
    not-held refusal. What this pins is the other direction: a pair the
    log somehow holds must be removable, and a guard copied across from
    the grant side would have made it permanent.
    """
    alice = uuid4()
    smuggled = Permission(principal_id=SYSTEM_PRINCIPAL_ID, command_name="RegisterActor")
    policy = Policy(id=uuid4(), permissions=_governing(alice) | {smuggled})

    (event,) = decide(policy, RevokePolicyPermission(policy.id, smuggled), now=_NOW)

    assert event.permission == smuggled
