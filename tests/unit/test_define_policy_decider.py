"""The decision that defining a policy produces.

Every case here turns on one idea: a policy is born able to be changed,
or it is not born. That rule arrived with granting. Before it, a policy
could not be edited at all, so a policy permitting nothing was merely
inert; now the same policy permits nothing AND permits nobody to fix
that, and the command that would put it right is the one nobody may
issue.
"""

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from keeper.authority.aggregates.policy import (
    GOVERNING_COMMAND_NAMES,
    Permission,
    Policy,
    PolicyAlreadyExistsError,
    PolicyDefined,
    PolicyWouldBeUngovernableError,
    SystemPrincipalCannotBeGrantedError,
)
from keeper.authority.features.define_policy import DefinePolicy, decide
from keeper.shared.reserved_ids import SYSTEM_PRINCIPAL_ID

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 9, 17, 12, 0, tzinfo=UTC)


def _governing(principal_id: UUID) -> frozenset[Permission]:
    """The smallest set a policy can be defined with.

    Derived from `GOVERNING_COMMAND_NAMES` rather than spelled out, so
    the day a second command joins the rule every test here starts
    exercising it instead of passing against yesterday's minimum.
    """
    return frozenset(
        Permission(principal_id=principal_id, command_name=name) for name in GOVERNING_COMMAND_NAMES
    )


def test_defining_a_policy_emits_one_event_carrying_the_permissions() -> None:
    new_id, alice = uuid4(), uuid4()
    granted = _governing(alice) | {Permission(principal_id=alice, command_name="RegisterActor")}

    events = decide(None, DefinePolicy(permissions=granted), now=_NOW, new_id=new_id)

    assert events == [PolicyDefined(policy_id=new_id, permissions=granted, occurred_at=_NOW)]


def test_defining_a_policy_with_no_permissions_is_refused() -> None:
    """A policy permitting nothing also permits nobody to repair it.

    This was allowed until granting existed. The change is deliberate
    and it is the reason the rule is here: the only route back from an
    empty policy is restarting the process with authorization off.
    """
    with pytest.raises(PolicyWouldBeUngovernableError):
        decide(None, DefinePolicy(permissions=frozenset()), now=_NOW, new_id=uuid4())


def test_defining_a_policy_nobody_can_change_is_refused() -> None:
    """Not empty, and still a brick.

    Alice may register actors and nobody may touch the rulebook, so it
    is frozen on the day it is written. An emptiness check alone would
    wave this through, which is why the rule asks which commands are
    named rather than how many permissions there are.
    """
    useful_but_ungovernable = frozenset(
        {Permission(principal_id=uuid4(), command_name="RegisterActor")}
    )
    with pytest.raises(PolicyWouldBeUngovernableError, match="GrantPolicyPermission"):
        decide(None, DefinePolicy(permissions=useful_but_ungovernable), now=_NOW, new_id=uuid4())


def test_defining_a_policy_that_grants_the_system_principal_is_refused() -> None:
    """The fallback identity may author a policy and may not be named by one."""
    granted = _governing(uuid4()) | {
        Permission(principal_id=SYSTEM_PRINCIPAL_ID, command_name="RegisterActor")
    }
    with pytest.raises(SystemPrincipalCannotBeGrantedError):
        decide(None, DefinePolicy(permissions=granted), now=_NOW, new_id=uuid4())


def test_defining_a_policy_onto_a_live_stream_is_refused() -> None:
    """The precondition is stated rather than assumed.

    A defining handler mints a fresh id, so this is unreachable through
    the ordinary path. It is here so a caller supplying its own id gets
    a refusal instead of a second genesis event on a live stream.
    """
    existing = Policy(id=uuid4(), permissions=frozenset())

    with pytest.raises(PolicyAlreadyExistsError):
        decide(existing, DefinePolicy(permissions=_governing(uuid4())), now=_NOW, new_id=uuid4())


def test_the_decider_takes_its_id_and_time_rather_than_finding_them() -> None:
    """Replay has to give the same events, so nothing may be invented.

    Called twice with the same inputs, including the same injected id
    and clock, the result is identical. A decider that reached for
    `uuid4()` or `datetime.now()` would pass every other test here and
    fail this one.
    """
    new_id, command = uuid4(), DefinePolicy(permissions=_governing(uuid4()))

    first = decide(None, command, now=_NOW, new_id=new_id)
    second = decide(None, command, now=_NOW, new_id=new_id)

    assert first == second
