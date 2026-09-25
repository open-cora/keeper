"""The grant handler, against in-process stores.

Update-style, so unlike the defining handler it loads and folds first
and appends at the version it read.

What that version buys is not tested here. Two writers racing on one
policy is a property of the store's UNIQUE constraint, and the in-memory
store is a dict behind a lock that fails differently. It is asserted
against real SQL in the integration tier instead.
"""

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from keeper.authority.aggregates.policy import (
    GOVERNING_COMMAND_NAMES,
    Permission,
    PolicyNotFoundError,
    load_policy,
)
from keeper.authority.errors import UnauthorizedError
from keeper.authority.features.define_policy import DefinePolicy
from keeper.authority.features.define_policy import bind as bind_define
from keeper.authority.features.grant_permission import GrantPolicyPermission
from keeper.authority.features.grant_permission import bind as bind_grant
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


async def _a_policy(deps: Kernel, administrator: UUID) -> UUID:
    """Define the smallest legal policy and return its id."""
    return await bind_define(deps)(
        DefinePolicy(
            permissions=frozenset(
                Permission(principal_id=administrator, command_name=name)
                for name in GOVERNING_COMMAND_NAMES
            )
        ),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )


async def test_granting_adds_the_pair_to_the_policy_that_can_be_read_back() -> None:
    deps = _kernel()
    alice = uuid4()
    policy_id = await _a_policy(deps, alice)
    added = Permission(principal_id=uuid4(), command_name="RegisterActor")

    await bind_grant(deps)(
        GrantPolicyPermission(policy_id, added), principal_id=alice, correlation_id=uuid4()
    )

    policy = await load_policy(deps.event_store, policy_id)
    assert policy is not None
    assert added in policy.permissions


async def test_granting_leaves_the_permissions_that_were_already_there() -> None:
    """A grant is a union, not an assignment."""
    deps = _kernel()
    alice = uuid4()
    policy_id = await _a_policy(deps, alice)
    before = await load_policy(deps.event_store, policy_id)
    assert before is not None

    await bind_grant(deps)(
        GrantPolicyPermission(
            policy_id, Permission(principal_id=uuid4(), command_name="RegisterActor")
        ),
        principal_id=alice,
        correlation_id=uuid4(),
    )

    after = await load_policy(deps.event_store, policy_id)
    assert after is not None
    assert before.permissions < after.permissions


async def test_granting_under_an_unknown_policy_id_is_refused() -> None:
    deps = _kernel()
    added = Permission(principal_id=uuid4(), command_name="RegisterActor")

    with pytest.raises(PolicyNotFoundError):
        await bind_grant(deps)(
            GrantPolicyPermission(uuid4(), added),
            principal_id=uuid4(),
            correlation_id=uuid4(),
        )


async def test_a_denied_caller_gets_an_error_and_writes_nothing() -> None:
    deps = _kernel()
    alice = uuid4()
    policy_id = await _a_policy(deps, alice)
    before = await load_policy(deps.event_store, policy_id)

    # The same store, so a write would be visible here; only the gate differs.
    denied = _kernel(authz=_DenyAllAuthorize(), event_store=deps.event_store)

    with pytest.raises(UnauthorizedError, match="not on the list"):
        await bind_grant(denied)(
            GrantPolicyPermission(
                policy_id, Permission(principal_id=uuid4(), command_name="RegisterActor")
            ),
            principal_id=uuid4(),
            correlation_id=uuid4(),
        )

    assert await load_policy(deps.event_store, policy_id) == before
