"""The registration handler, against in-process stores.

The handler authorizes, mints an id, decides, and appends. The one worth
reading is `test_a_denied_caller_gets_an_error_and_writes_nothing`: it
asserts no id was minted at all, not merely that no event landed, which
is the difference between a gate placed before the work and one placed
after it.
"""

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from keeper.access.aggregates.actor import ACTOR_STREAM_TYPE, Actor, load_actor
from keeper.access.errors import UnauthorizedError
from keeper.access.features.register_actor import RegisterActor, bind
from keeper.infrastructure.adapters.in_memory_event_store import InMemoryEventStore
from keeper.infrastructure.deps import make_inmemory_kernel
from keeper.infrastructure.kernel import Kernel
from keeper.infrastructure.ports import AllowAllAuthorize, Deny
from keeper.infrastructure.ports.authorize import AuthzResult
from keeper.infrastructure.settings import Settings
from keeper.shared.reserved_ids import NIL_SENTINEL_ID

pytestmark = pytest.mark.unit

_WHEN = datetime(2026, 9, 17, 12, 0, tzinfo=UTC)


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


async def test_registering_returns_the_id_the_actor_can_be_loaded_by() -> None:
    deps = _kernel()
    handler = bind(deps)

    actor_id = await handler(RegisterActor(), principal_id=uuid4(), correlation_id=uuid4())

    assert await load_actor(deps.event_store, actor_id) == Actor(id=actor_id, active=True)


async def test_the_appended_event_records_the_principal_that_issued_the_command() -> None:
    deps = _kernel()
    handler = bind(deps)
    caller = uuid4()

    actor_id = await handler(RegisterActor(), principal_id=caller, correlation_id=uuid4())

    rows, _version = await deps.event_store.load(ACTOR_STREAM_TYPE, actor_id)
    assert rows[0].principal_id == caller


async def test_a_denied_caller_gets_an_error_and_writes_nothing() -> None:
    deps = _kernel(authz=_DenyAllAuthorize())
    handler = bind(deps)

    with pytest.raises(UnauthorizedError, match="not on the list"):
        await handler(RegisterActor(), principal_id=uuid4(), correlation_id=uuid4())

    generator = deps.id_generator
    assert isinstance(generator, _CountingIdGenerator)
    assert generator.issued == [], "authorization must be decided before an id is minted"
