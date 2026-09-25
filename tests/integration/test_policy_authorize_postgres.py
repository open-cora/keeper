"""The authorization decision against real rows, across both contexts.

The adapter's unit tests fold aggregates an in-memory store handed
straight back. Here the pair it looks up was rendered to a sorted list
of two-element arrays, written, read and rebuilt, and the actor it reads
came back through the same translation, so a principal id that survives
as a string rather than a UUID stops matching here and nowhere else.

Its own file rather than a guest in the Authority slices, because the
decision genuinely spans two bounded contexts: Authority says permitted,
Access says standing, and neither half is the subject on its own. The
file therefore wires both bundles onto one kernel, which is what the
application does.
"""

from uuid import UUID, uuid4

import asyncpg
import pytest

from keeper.access import AccessHandlers, wire_access
from keeper.access.features.deactivate_actor import DeactivateActor
from keeper.access.features.reactivate_actor import ReactivateActor
from keeper.access.features.register_actor import RegisterActor
from keeper.authority import wire_authority
from keeper.authority.adapters import PolicyAuthorize
from keeper.authority.aggregates.policy import GOVERNING_COMMAND_NAMES, Permission, load_policy
from keeper.authority.features.define_policy import DefinePolicy
from keeper.authority.features.grant_permission import GrantPolicyPermission
from keeper.authority.wire import AuthorityHandlers
from keeper.infrastructure.adapters.postgres_event_store import PostgresEventStore
from keeper.infrastructure.deps import make_postgres_kernel
from keeper.infrastructure.ports import Allow, Deny
from keeper.infrastructure.ports.authorize import AllowAllAuthorize
from keeper.infrastructure.ports.clock import SystemClock
from keeper.infrastructure.ports.id_generator import UUIDv7Generator
from keeper.infrastructure.settings import Settings

pytestmark = [pytest.mark.integration]

_GOVERNING = sorted(GOVERNING_COMMAND_NAMES)[0]


@pytest.fixture
def bundles(db_pool: asyncpg.Pool) -> tuple[AccessHandlers, AuthorityHandlers]:
    """Both contexts on one kernel, wired under the permissive adapter.

    The writes that set a scenario up run under `AllowAllAuthorize`,
    which is the bootstrap posture. The adapter under test is built
    separately against the same pool, which is what a restart does.
    """
    kernel = make_postgres_kernel(
        db_pool,
        settings=Settings(app_env="test"),
        clock=SystemClock(),
        id_generator=UUIDv7Generator(),
        authz=AllowAllAuthorize(),
    )
    return wire_access(kernel), wire_authority(kernel)


async def _an_authorized_actor(
    bundles: tuple[AccessHandlers, AuthorityHandlers],
) -> tuple[UUID, UUID]:
    """Register an actor, then author a policy permitting it. In that order."""
    access, authority = bundles
    actor_id = await access.register_actor(
        RegisterActor(), principal_id=uuid4(), correlation_id=uuid4()
    )
    policy_id = await authority.define_policy(
        DefinePolicy(
            permissions=frozenset(
                Permission(principal_id=actor_id, command_name=name)
                for name in GOVERNING_COMMAND_NAMES
            )
        ),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )
    return actor_id, policy_id


async def test_a_permitted_active_actor_is_allowed_from_the_stored_rows(
    bundles: tuple[AccessHandlers, AuthorityHandlers], db_pool: asyncpg.Pool
) -> None:
    alice, policy_id = await _an_authorized_actor(bundles)
    _access, authority = bundles
    bob = await bundles[0].register_actor(
        RegisterActor(), principal_id=uuid4(), correlation_id=uuid4()
    )
    await authority.grant_permission(
        GrantPolicyPermission(
            policy_id, Permission(principal_id=bob, command_name="RegisterActor")
        ),
        principal_id=alice,
        correlation_id=uuid4(),
    )

    authz = PolicyAuthorize(PostgresEventStore(db_pool), policy_id)

    assert isinstance(await authz.authorize(bob, "RegisterActor"), Allow)
    assert isinstance(await authz.authorize(alice, "RegisterActor"), Deny)
    assert isinstance(await authz.authorize(alice, _GOVERNING), Allow)


async def test_the_switch_in_access_decides_authority_and_leaves_it_unedited(
    bundles: tuple[AccessHandlers, AuthorityHandlers], db_pool: asyncpg.Pool
) -> None:
    """The whole feature in one walk, over two streams in one database.

    Allow, deactivate, deny, reactivate, allow, with the rulebook
    identical at the end. Nothing in memory can show this: the two
    aggregates live in different contexts and the only thing joining
    them is the adapter reading both.
    """
    access, _authority = bundles
    alice, policy_id = await _an_authorized_actor(bundles)
    store = PostgresEventStore(db_pool)
    authz = PolicyAuthorize(store, policy_id)
    before = await load_policy(store, policy_id)

    assert isinstance(await authz.authorize(alice, _GOVERNING), Allow)

    await access.deactivate_actor(
        DeactivateActor(actor_id=alice), principal_id=uuid4(), correlation_id=uuid4()
    )
    assert isinstance(await authz.authorize(alice, _GOVERNING), Deny)

    await access.reactivate_actor(
        ReactivateActor(actor_id=alice), principal_id=uuid4(), correlation_id=uuid4()
    )
    assert isinstance(await authz.authorize(alice, _GOVERNING), Allow)

    assert await load_policy(store, policy_id) == before


async def test_a_permission_naming_an_unregistered_id_authorizes_nothing(
    bundles: tuple[AccessHandlers, AuthorityHandlers], db_pool: asyncpg.Pool
) -> None:
    """The bootstrap mistake, against the database it would be made in."""
    _access, authority = bundles
    ghost = uuid4()
    policy_id = await authority.define_policy(
        DefinePolicy(
            permissions=frozenset(
                Permission(principal_id=ghost, command_name=name)
                for name in GOVERNING_COMMAND_NAMES
            )
        ),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )

    authz = PolicyAuthorize(PostgresEventStore(db_pool), policy_id)

    assert isinstance(await authz.authorize(ghost, _GOVERNING), Deny)
