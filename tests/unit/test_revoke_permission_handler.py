"""The revoke handler, against in-process stores.

Update-style, so like the granting handler it loads and folds first and
appends at the version it read.

The policies here are built by running the real defining and granting
handlers rather than by constructing state, so what is revoked is a
permission that went through the whole write path. A revoke that only
ever removes a hand-built pair would not notice a payload the grant side
writes and the revoke side cannot find.
"""

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from keeper.authority.aggregates.policy import (
    GOVERNING_COMMAND_NAMES,
    Permission,
    PolicyNotFoundError,
    PolicyWouldBeUngovernableError,
    load_policy,
)
from keeper.authority.errors import UnauthorizedError
from keeper.authority.features.define_policy import DefinePolicy
from keeper.authority.features.define_policy import bind as bind_define
from keeper.authority.features.grant_permission import GrantPolicyPermission
from keeper.authority.features.grant_permission import bind as bind_grant
from keeper.authority.features.revoke_permission import RevokePolicyPermission
from keeper.authority.features.revoke_permission import bind as bind_revoke
from keeper.infrastructure.adapters.in_memory_event_store import InMemoryEventStore
from keeper.infrastructure.deps import make_inmemory_kernel
from keeper.infrastructure.kernel import Kernel
from keeper.infrastructure.ports import AllowAllAuthorize, Deny
from keeper.infrastructure.ports.authorize import AuthzResult
from keeper.infrastructure.ports.event_store import EventStore
from keeper.infrastructure.ports.id_generator import UUIDv7Generator
from keeper.infrastructure.settings import Settings
from keeper.shared.reserved_ids import NIL_SENTINEL_ID

pytestmark = pytest.mark.unit

_WHEN = datetime(2026, 9, 17, 12, 0, tzinfo=UTC)


class _FixedClock:
    def now(self) -> datetime:
        return _WHEN


class _DenyAllAuthorize:
    async def authorize(
        self,
        principal_id: UUID,
        command_name: str,
        surface_id: UUID = NIL_SENTINEL_ID,
    ) -> AuthzResult:
        _ = (principal_id, command_name, surface_id)
        return Deny(reason="not on the list")


def _kernel(*, authz: object | None = None, event_store: EventStore | None = None) -> Kernel:
    return make_inmemory_kernel(
        settings=Settings(app_env="test"),
        clock=_FixedClock(),
        id_generator=UUIDv7Generator(),
        authz=authz or AllowAllAuthorize(),  # pyright: ignore[reportArgumentType]
        event_store=event_store or InMemoryEventStore(),
    )


def _governing(principal_id: UUID) -> frozenset[Permission]:
    return frozenset(
        Permission(principal_id=principal_id, command_name=name) for name in GOVERNING_COMMAND_NAMES
    )


async def _a_policy(deps: Kernel, administrator: UUID) -> UUID:
    """Define the smallest legal policy and return its id."""
    return await bind_define(deps)(
        DefinePolicy(permissions=_governing(administrator)),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )


async def test_revoking_removes_a_granted_pair_from_the_policy_read_back() -> None:
    deps = _kernel()
    alice = uuid4()
    policy_id = await _a_policy(deps, alice)
    granted = Permission(principal_id=uuid4(), command_name="RegisterActor")
    await bind_grant(deps)(
        GrantPolicyPermission(policy_id, granted), principal_id=alice, correlation_id=uuid4()
    )

    await bind_revoke(deps)(
        RevokePolicyPermission(policy_id, granted), principal_id=alice, correlation_id=uuid4()
    )

    policy = await load_policy(deps.event_store, policy_id)
    assert policy is not None
    assert granted not in policy.permissions


async def test_revoking_leaves_the_permissions_that_were_not_named() -> None:
    """A revoke is a difference, not an assignment."""
    deps = _kernel()
    alice = uuid4()
    policy_id = await _a_policy(deps, alice)
    kept = Permission(principal_id=uuid4(), command_name="RegisterActor")
    dropped = Permission(principal_id=uuid4(), command_name="GetActor")
    for permission in (kept, dropped):
        await bind_grant(deps)(
            GrantPolicyPermission(policy_id, permission),
            principal_id=alice,
            correlation_id=uuid4(),
        )

    await bind_revoke(deps)(
        RevokePolicyPermission(policy_id, dropped), principal_id=alice, correlation_id=uuid4()
    )

    policy = await load_policy(deps.event_store, policy_id)
    assert policy is not None
    assert policy.permissions == _governing(alice) | {kept}


async def test_revoking_under_an_unknown_policy_id_is_refused() -> None:
    deps = _kernel()
    gone = Permission(principal_id=uuid4(), command_name="RegisterActor")

    with pytest.raises(PolicyNotFoundError):
        await bind_revoke(deps)(
            RevokePolicyPermission(uuid4(), gone),
            principal_id=uuid4(),
            correlation_id=uuid4(),
        )


async def test_an_administrator_cannot_revoke_their_own_last_governing_permission() -> None:
    """The guard is reachable through the whole write path, not just the decider.

    A handler that loaded the wrong stream, or folded and then decided
    against a state it had already discarded, would let this through
    while every decider test stayed green.
    """
    deps = _kernel()
    alice = uuid4()
    policy_id = await _a_policy(deps, alice)
    before = await load_policy(deps.event_store, policy_id)
    assert before is not None
    last = next(iter(before.permissions))

    with pytest.raises(PolicyWouldBeUngovernableError):
        await bind_revoke(deps)(
            RevokePolicyPermission(policy_id, last),
            principal_id=alice,
            correlation_id=uuid4(),
        )

    assert await load_policy(deps.event_store, policy_id) == before


async def test_a_denied_caller_gets_an_error_and_writes_nothing() -> None:
    deps = _kernel()
    alice = uuid4()
    policy_id = await _a_policy(deps, alice)
    granted = Permission(principal_id=uuid4(), command_name="RegisterActor")
    await bind_grant(deps)(
        GrantPolicyPermission(policy_id, granted), principal_id=alice, correlation_id=uuid4()
    )
    before = await load_policy(deps.event_store, policy_id)

    # The same store, so a write would be visible here; only the gate differs.
    denied = _kernel(authz=_DenyAllAuthorize(), event_store=deps.event_store)

    with pytest.raises(UnauthorizedError, match="not on the list"):
        await bind_revoke(denied)(
            RevokePolicyPermission(policy_id, granted),
            principal_id=uuid4(),
            correlation_id=uuid4(),
        )

    assert await load_policy(deps.event_store, policy_id) == before
