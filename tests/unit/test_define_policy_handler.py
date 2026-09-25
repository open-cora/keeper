"""The definition handler, against in-process stores.

The one worth reading is the bootstrap test at the end. Defining the
first policy happens under `AllowAllAuthorize`, performed by whichever
principal the deployment is running as, and that principal need not
appear anywhere in the permissions it writes. Those are two different
fields and the whole bootstrap depends on their being different.
"""

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from keeper.authority.aggregates.policy import (
    GOVERNING_COMMAND_NAMES,
    POLICY_STREAM_TYPE,
    Permission,
    Policy,
    load_policy,
)
from keeper.authority.errors import UnauthorizedError
from keeper.authority.features.define_policy import DefinePolicy, bind
from keeper.infrastructure.adapters.in_memory_event_store import InMemoryEventStore
from keeper.infrastructure.deps import make_inmemory_kernel
from keeper.infrastructure.kernel import Kernel
from keeper.infrastructure.ports import AllowAllAuthorize, Deny
from keeper.infrastructure.ports.authorize import AuthzResult
from keeper.infrastructure.settings import Settings
from keeper.shared.reserved_ids import NIL_SENTINEL_ID, SYSTEM_PRINCIPAL_ID

pytestmark = pytest.mark.unit

_WHEN = datetime(2026, 9, 17, 12, 0, tzinfo=UTC)


def _governing(principal_id: UUID) -> frozenset[Permission]:
    """The smallest permission set a policy can now be defined with."""
    return frozenset(
        Permission(principal_id=principal_id, command_name=name) for name in GOVERNING_COMMAND_NAMES
    )


class _FixedClock:
    def now(self) -> datetime:
        return _WHEN


class _CountingIdGenerator:
    """Hands out predictable ids so a test can name the one it expects."""

    def __init__(self) -> None:
        self.issued: list[UUID] = []

    def new_id(self) -> UUID:
        minted = uuid4()
        self.issued.append(minted)
        return minted


class _DenyAllAuthorize:
    async def authorize(
        self,
        principal_id: UUID,
        command_name: str,
        surface_id: UUID = NIL_SENTINEL_ID,
    ) -> AuthzResult:
        _ = (principal_id, command_name, surface_id)
        return Deny(reason="not on the list")


def _kernel(
    *,
    authz: object | None = None,
    event_store: InMemoryEventStore | None = None,
) -> Kernel:
    return make_inmemory_kernel(
        settings=Settings(app_env="test"),
        clock=_FixedClock(),
        id_generator=_CountingIdGenerator(),
        authz=authz or AllowAllAuthorize(),  # pyright: ignore[reportArgumentType]
        event_store=event_store or InMemoryEventStore(),
    )


async def test_defining_returns_the_id_the_policy_can_be_loaded_by() -> None:
    deps = _kernel()
    handler = bind(deps)
    alice = uuid4()
    granted = _governing(alice) | {Permission(principal_id=alice, command_name="RegisterActor")}

    policy_id = await handler(
        DefinePolicy(permissions=granted), principal_id=uuid4(), correlation_id=uuid4()
    )

    assert await load_policy(deps.event_store, policy_id) == Policy(
        id=policy_id, permissions=granted
    )


async def test_the_appended_event_records_the_principal_that_issued_the_command() -> None:
    deps = _kernel()
    handler = bind(deps)
    caller = uuid4()

    policy_id = await handler(
        DefinePolicy(permissions=_governing(uuid4())),
        principal_id=caller,
        correlation_id=uuid4(),
    )

    rows, _version = await deps.event_store.load(POLICY_STREAM_TYPE, policy_id)
    assert rows[0].principal_id == caller


async def test_a_denied_caller_gets_an_error_and_writes_nothing() -> None:
    deps = _kernel(authz=_DenyAllAuthorize())
    handler = bind(deps)

    with pytest.raises(UnauthorizedError, match="not on the list"):
        await handler(
            DefinePolicy(permissions=_governing(uuid4())),
            principal_id=uuid4(),
            correlation_id=uuid4(),
        )

    generator = deps.id_generator
    assert isinstance(generator, _CountingIdGenerator)
    assert generator.issued == [], "authorization must be decided before an id is minted"


async def test_the_system_principal_can_author_a_policy_granting_only_others() -> None:
    """The bootstrap, asserted rather than described in a runbook.

    A fresh deployment runs under `AllowAllAuthorize` with no policy at
    all, and the party performing the first definition is the system
    principal. It appears in the envelope as who did it, and nowhere in
    the permissions, which name real registered actors instead.

    This is what makes it safe to refuse the system principal as a
    GRANTEE later: nothing about creating the first rulebook requires
    granting anything to the party creating it.
    """
    deps = _kernel()
    handler = bind(deps)
    administrator = uuid4()
    granted = _governing(administrator)

    policy_id = await handler(
        DefinePolicy(permissions=granted),
        principal_id=SYSTEM_PRINCIPAL_ID,
        correlation_id=uuid4(),
    )

    rows, _version = await deps.event_store.load(POLICY_STREAM_TYPE, policy_id)
    assert rows[0].principal_id == SYSTEM_PRINCIPAL_ID, "the system principal performed it"

    policy = await load_policy(deps.event_store, policy_id)
    assert policy is not None
    granted_ids = {p.principal_id for p in policy.permissions}
    assert granted_ids == {administrator}
    assert SYSTEM_PRINCIPAL_ID not in granted_ids, "and was granted nothing by doing so"
