"""The real authorization adapter, against state the writes produced.

Everything else in this repository runs against `AllowAllAuthorize`,
which answers the same way whatever it is handed. This file is the only
place a denial is a decision rather than a stub's return value.

Both aggregates here are written through the real handlers rather than
constructed. The pair the adapter looks up has to be the pair a grant
stores, and the actor it reads has to be the actor a registration wrote,
so a test building either side in memory would agree with itself through
a write path it never took.

`_an_authorized_actor` runs the bootstrap in the order a deployment has
to: register the actor FIRST, then author a policy naming the id that
registration minted. The other order is unreachable, because the
registering handler mints the id rather than accepting one, and that is
the same constraint an operator meets.
"""

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from keeper.access.features.deactivate_actor import DeactivateActor
from keeper.access.features.deactivate_actor import bind as bind_deactivate
from keeper.access.features.reactivate_actor import ReactivateActor
from keeper.access.features.reactivate_actor import bind as bind_reactivate
from keeper.access.features.register_actor import RegisterActor
from keeper.access.features.register_actor import bind as bind_register
from keeper.authority.adapters import PolicyAuthorize, build_authorize
from keeper.authority.aggregates.policy import (
    GOVERNING_COMMAND_NAMES,
    Permission,
    load_policy,
)
from keeper.authority.features.define_policy import DefinePolicy
from keeper.authority.features.define_policy import bind as bind_define
from keeper.authority.features.grant_permission import GrantPolicyPermission
from keeper.authority.features.grant_permission import bind as bind_grant
from keeper.infrastructure.adapters.in_memory_event_store import InMemoryEventStore
from keeper.infrastructure.deps import make_inmemory_kernel
from keeper.infrastructure.kernel import Kernel
from keeper.infrastructure.ports import Allow, AllowAllAuthorize, Deny
from keeper.infrastructure.ports.id_generator import UUIDv7Generator
from keeper.infrastructure.settings import Settings
from keeper.shared.reserved_ids import SYSTEM_PRINCIPAL_ID

pytestmark = pytest.mark.unit

_WHEN = datetime(2026, 9, 17, 12, 0, tzinfo=UTC)


class _FixedClock:
    def now(self) -> datetime:
        return _WHEN


def _kernel(event_store: InMemoryEventStore) -> Kernel:
    return make_inmemory_kernel(
        settings=Settings(app_env="test"),
        clock=_FixedClock(),
        id_generator=UUIDv7Generator(),
        authz=AllowAllAuthorize(),
        event_store=event_store,
    )


def _governing(principal_id: UUID) -> frozenset[Permission]:
    return frozenset(
        Permission(principal_id=principal_id, command_name=name) for name in GOVERNING_COMMAND_NAMES
    )


async def _a_policy(deps: Kernel, administrator: UUID, *also: Permission) -> UUID:
    """Author a policy holding the governing set plus whatever else is named."""
    return await bind_define(deps)(
        DefinePolicy(permissions=_governing(administrator) | frozenset(also)),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )


async def _an_actor(deps: Kernel) -> UUID:
    """Register an actor and return the id that registration minted."""
    return await bind_register(deps)(RegisterActor(), principal_id=uuid4(), correlation_id=uuid4())


async def _an_authorized_actor(deps: Kernel) -> tuple[UUID, UUID]:
    """An active actor, and a policy that permits them the governing set."""
    actor_id = await _an_actor(deps)
    return actor_id, await _a_policy(deps, actor_id)


async def test_a_permitted_pair_from_an_active_actor_is_allowed() -> None:
    store = InMemoryEventStore()
    alice, policy_id = await _an_authorized_actor(_kernel(store))

    decision = await PolicyAuthorize(store, policy_id).authorize(
        principal_id=alice, command_name=sorted(GOVERNING_COMMAND_NAMES)[0]
    )

    assert isinstance(decision, Allow)


async def test_a_pair_the_policy_does_not_hold_is_denied() -> None:
    """Deny by default: absence from the rulebook is a refusal, not a gap."""
    store = InMemoryEventStore()
    alice = uuid4()
    policy_id = await _a_policy(_kernel(store), alice)

    decision = await PolicyAuthorize(store, policy_id).authorize(
        principal_id=alice, command_name="RegisterActor"
    )

    assert isinstance(decision, Deny)


async def test_the_right_principal_with_the_wrong_command_is_denied() -> None:
    """The pair is the unit, so holding one half permits nothing."""
    store = InMemoryEventStore()
    alice = uuid4()
    policy_id = await _a_policy(
        _kernel(store), alice, Permission(principal_id=alice, command_name="RegisterActor")
    )

    decision = await PolicyAuthorize(store, policy_id).authorize(
        principal_id=alice, command_name="DeactivateActor"
    )

    assert isinstance(decision, Deny)


async def test_the_right_command_from_the_wrong_principal_is_denied() -> None:
    """The other half of the same rule, which one test cannot cover.

    A lookup keyed on the command alone passes the test above and fails
    this one; a lookup keyed on the principal alone does the reverse.
    """
    store = InMemoryEventStore()
    alice, mallory = uuid4(), uuid4()
    policy_id = await _a_policy(
        _kernel(store), alice, Permission(principal_id=alice, command_name="RegisterActor")
    )

    decision = await PolicyAuthorize(store, policy_id).authorize(
        principal_id=mallory, command_name="RegisterActor"
    )

    assert isinstance(decision, Deny)


async def test_the_system_principal_is_denied_everything() -> None:
    """The cost of the cutover, asserted rather than assumed.

    Under `AllowAllAuthorize` an unauthenticated request runs as the
    system principal and is permitted everything. Under this adapter it
    is permitted nothing, because it cannot hold a permission and no
    branch here makes an exception for it. A deployment that switches
    adapters without authenticating its callers stops serving.
    """
    store = InMemoryEventStore()
    policy_id = await _a_policy(_kernel(store), uuid4())

    decision = await PolicyAuthorize(store, policy_id).authorize(
        principal_id=SYSTEM_PRINCIPAL_ID, command_name=sorted(GOVERNING_COMMAND_NAMES)[0]
    )

    assert isinstance(decision, Deny)


async def test_a_configured_policy_that_does_not_exist_denies_every_command() -> None:
    """A typo in one environment variable is an outage, never an open door."""
    store = InMemoryEventStore()
    await _a_policy(_kernel(store), uuid4())

    decision = await PolicyAuthorize(store, uuid4()).authorize(
        principal_id=uuid4(), command_name="RegisterActor"
    )

    assert isinstance(decision, Deny)


async def test_the_denial_names_the_command_and_not_the_policy() -> None:
    """The reason reaches a caller this deployment has just refused.

    They already know which command they sent, so naming it helps. The
    policy id is deployment detail and the permissions are the map an
    unauthorized caller would most like; both stay in the log.
    """
    store = InMemoryEventStore()
    alice = uuid4()
    policy_id = await _a_policy(_kernel(store), alice)

    decision = await PolicyAuthorize(store, policy_id).authorize(
        principal_id=alice, command_name="RegisterActor"
    )

    assert isinstance(decision, Deny)
    assert "RegisterActor" in decision.reason
    assert str(policy_id) not in decision.reason
    assert str(alice) not in decision.reason


async def test_a_grant_is_visible_to_the_very_next_decision() -> None:
    """No cache on the policy, asserted so adding one has to come past here.

    The adapter folds the policy per call, so a permission granted after
    it was constructed decides the next request. The moment that stops
    being true, a grant an operator has just made and verified will not
    take effect, and this is the test that says so.
    """
    store = InMemoryEventStore()
    deps = _kernel(store)
    alice, policy_id = await _an_authorized_actor(deps)
    bob = await _an_actor(deps)
    adapter = PolicyAuthorize(store, policy_id)
    assert isinstance(await adapter.authorize(bob, "RegisterActor"), Deny)

    await bind_grant(deps)(
        GrantPolicyPermission(
            policy_id, Permission(principal_id=bob, command_name="RegisterActor")
        ),
        principal_id=alice,
        correlation_id=uuid4(),
    )

    assert isinstance(await adapter.authorize(bob, "RegisterActor"), Allow)


def test_the_factory_hands_back_the_permissive_adapter_when_no_policy_is_configured() -> None:
    """The bootstrap posture, and the one a production tier refuses."""
    built = build_authorize(Settings(app_env="test"), InMemoryEventStore())
    assert isinstance(built, AllowAllAuthorize)


def test_the_factory_builds_the_policy_adapter_once_a_policy_is_configured() -> None:
    built = build_authorize(Settings(app_env="test", authz_policy_id=uuid4()), InMemoryEventStore())
    assert isinstance(built, PolicyAuthorize)


async def test_a_permitted_principal_with_no_actor_behind_it_is_denied() -> None:
    """A permission can name an id Access has never heard of.

    `Permission` stores a bare UUID with nothing looked up behind it, so
    granting a mistyped id succeeds and produces a rulebook entry that
    must never authorize anything. It is also the shape of the bootstrap
    mistake: author the policy before registering the administrator and
    this is what the deployment does to itself.
    """
    store = InMemoryEventStore()
    ghost = uuid4()
    policy_id = await _a_policy(_kernel(store), ghost)

    decision = await PolicyAuthorize(store, policy_id).authorize(
        principal_id=ghost, command_name=sorted(GOVERNING_COMMAND_NAMES)[0]
    )

    assert isinstance(decision, Deny)
    assert "actor" in decision.reason


async def test_a_deactivated_actor_is_denied_what_the_policy_still_permits() -> None:
    """The check this slice exists for.

    Authentication never consults the Actor aggregate, so without this
    the switch in Access takes nothing away and the only way to stop a
    deactivated actor is to revoke every permission they hold.
    """
    store = InMemoryEventStore()
    deps = _kernel(store)
    alice, policy_id = await _an_authorized_actor(deps)
    command = sorted(GOVERNING_COMMAND_NAMES)[0]
    assert isinstance(await PolicyAuthorize(store, policy_id).authorize(alice, command), Allow)

    await bind_deactivate(deps)(
        DeactivateActor(actor_id=alice), principal_id=uuid4(), correlation_id=uuid4()
    )

    decision = await PolicyAuthorize(store, policy_id).authorize(alice, command)
    assert isinstance(decision, Deny)
    assert "active" in decision.reason


async def test_a_deactivation_is_visible_to_the_very_next_decision() -> None:
    """No cache on the actor either, which is the half that must be prompt.

    A stale policy delays a grant taking effect. A stale actor keeps
    somebody switched off still working, which is the direction that
    matters, so the adapter folds both per call.
    """
    store = InMemoryEventStore()
    deps = _kernel(store)
    alice, policy_id = await _an_authorized_actor(deps)
    command = sorted(GOVERNING_COMMAND_NAMES)[0]
    adapter = PolicyAuthorize(store, policy_id)
    assert isinstance(await adapter.authorize(alice, command), Allow)

    await bind_deactivate(deps)(
        DeactivateActor(actor_id=alice), principal_id=uuid4(), correlation_id=uuid4()
    )

    assert isinstance(await adapter.authorize(alice, command), Deny)


async def test_deactivating_an_actor_leaves_their_permissions_in_the_policy() -> None:
    """The direction: Authority reads Access and Access never writes Authority.

    A cascade would have Access's switch rewrite Authority's rulebook,
    turning a reversible act into one nobody can undo without knowing
    what was there to begin with. The permission stays and stops being
    effective, which are different things.
    """
    store = InMemoryEventStore()
    deps = _kernel(store)
    alice, policy_id = await _an_authorized_actor(deps)
    before = await load_policy(store, policy_id)

    await bind_deactivate(deps)(
        DeactivateActor(actor_id=alice), principal_id=uuid4(), correlation_id=uuid4()
    )

    assert await load_policy(store, policy_id) == before


async def test_reactivating_restores_authority_with_nothing_re_granted() -> None:
    """The payoff of not cascading, which one direction alone cannot show.

    The test above says the rulebook was not edited. This says the
    un-edited rulebook still works, which is the fact an operator
    switching someone back on is relying on.
    """
    store = InMemoryEventStore()
    deps = _kernel(store)
    alice, policy_id = await _an_authorized_actor(deps)
    command = sorted(GOVERNING_COMMAND_NAMES)[0]
    adapter = PolicyAuthorize(store, policy_id)
    await bind_deactivate(deps)(
        DeactivateActor(actor_id=alice), principal_id=uuid4(), correlation_id=uuid4()
    )
    assert isinstance(await adapter.authorize(alice, command), Deny)

    await bind_reactivate(deps)(
        ReactivateActor(actor_id=alice), principal_id=uuid4(), correlation_id=uuid4()
    )

    assert isinstance(await adapter.authorize(alice, command), Allow)


async def test_an_unpermitted_caller_is_refused_before_access_is_consulted() -> None:
    """The order of the two checks, asserted through the reason.

    A caller the rulebook does not name is refused without their actor
    record being read, so they learn whether they were permitted and
    nothing about whether this system has heard of them. Reversing the
    order would tell an unregistered stranger exactly that.
    """
    store = InMemoryEventStore()
    _alice, policy_id = await _an_authorized_actor(_kernel(store))
    stranger = uuid4()

    decision = await PolicyAuthorize(store, policy_id).authorize(stranger, "RegisterActor")

    assert isinstance(decision, Deny)
    assert decision.reason == "not permitted to issue RegisterActor"
