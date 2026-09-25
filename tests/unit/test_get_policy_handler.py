"""The read handler, against in-process stores.

A read decides nothing, so there is no decider file and no decider test.
What is left to get wrong is the gate, the refusal when the stream is
empty, and whether the fold the handler returns is the one the writes
produced. The last of those is why the policies here are built by
running the real writing handlers rather than by constructing state: a
read that only ever sees hand-built objects cannot notice a write path
it disagrees with.
"""

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from keeper.authority.aggregates.policy import (
    GOVERNING_COMMAND_NAMES,
    Permission,
    PolicyNotFoundError,
)
from keeper.authority.errors import UnauthorizedError
from keeper.authority.features.define_policy import DefinePolicy
from keeper.authority.features.define_policy import bind as bind_define
from keeper.authority.features.get_policy import GetPolicy
from keeper.authority.features.get_policy import bind as bind_get
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
    return await bind_define(deps)(
        DefinePolicy(permissions=_governing(administrator)),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )


async def test_reading_returns_the_permissions_the_policy_was_defined_with() -> None:
    deps = _kernel()
    alice = uuid4()
    policy_id = await _a_policy(deps, alice)

    policy = await bind_get(deps)(GetPolicy(policy_id), principal_id=alice, correlation_id=uuid4())

    assert policy.id == policy_id
    assert policy.permissions == _governing(alice)


async def test_reading_reflects_a_grant_and_a_revocation_that_followed() -> None:
    """The read folds the whole stream, not just its genesis.

    A read wired to the definition alone, or to a stream type the
    writing slices do not use, comes back with the starting set and
    looks entirely reasonable.
    """
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

    policy = await bind_get(deps)(GetPolicy(policy_id), principal_id=alice, correlation_id=uuid4())

    assert policy.permissions == _governing(alice) | {kept}


async def test_reading_a_policy_that_was_never_defined_is_refused() -> None:
    deps = _kernel()

    with pytest.raises(PolicyNotFoundError):
        await bind_get(deps)(GetPolicy(uuid4()), principal_id=uuid4(), correlation_id=uuid4())


async def test_a_denied_caller_learns_nothing_about_the_policy() -> None:
    """A read is refused like a write. Nothing is written either way, so the
    only evidence a gate ran at all is that the answer never arrives."""
    deps = _kernel()
    policy_id = await _a_policy(deps, uuid4())
    denied = _kernel(authz=_DenyAllAuthorize(), event_store=deps.event_store)

    with pytest.raises(UnauthorizedError, match="not on the list"):
        await bind_get(denied)(GetPolicy(policy_id), principal_id=uuid4(), correlation_id=uuid4())
