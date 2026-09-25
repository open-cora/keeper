"""The reactivation handler, against in-process stores.

Update-style, like its inverse. Two are worth reading.

`test_the_full_cycle_leaves_every_switch_on_the_stream`: the fold
reports where an actor ended up, and the stream is what says how it got
there. An implementation that mutated a row instead of appending would
satisfy the state assertions and lose the history.

`test_the_append_uses_the_version_the_load_returned`: every other path
here reactivates a stream sitting at version 2, where a handler passing
the constant 2 behaves identically to one passing what it read. That
one moves the stream first, so the two come apart.
"""

from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from keeper.access.aggregates.actor import (
    ACTOR_STREAM_TYPE,
    Actor,
    ActorCannotBeReactivatedError,
    ActorNotFoundError,
    load_actor,
    to_payload,
)
from keeper.access.aggregates.actor.events import (
    ActorDeactivated,
    ActorReactivated,
    ActorRegistered,
)
from keeper.access.errors import UnauthorizedError
from keeper.access.features.deactivate_actor import DeactivateActor
from keeper.access.features.deactivate_actor import bind as bind_deactivate
from keeper.access.features.reactivate_actor import ReactivateActor, bind
from keeper.infrastructure.adapters.in_memory_event_store import InMemoryEventStore
from keeper.infrastructure.deps import make_inmemory_kernel
from keeper.infrastructure.kernel import Kernel
from keeper.infrastructure.ports import AllowAllAuthorize, Deny
from keeper.infrastructure.ports.authorize import AuthzResult
from keeper.infrastructure.ports.event_store import NewEvent
from keeper.infrastructure.settings import Settings
from keeper.infrastructure.slices.envelope import to_new_event
from keeper.shared.reserved_ids import NIL_SENTINEL_ID

pytestmark = pytest.mark.unit

_WHEN = datetime(2026, 9, 17, 12, 0, tzinfo=UTC)


class _FixedClock:
    def now(self) -> datetime:
        return _WHEN


class _Uuid4Generator:
    def new_id(self) -> UUID:
        return uuid4()


class _DenyAllAuthorize:
    async def authorize(
        self,
        principal_id: UUID,
        command_name: str,
        surface_id: UUID = NIL_SENTINEL_ID,
    ) -> AuthzResult:
        _ = (principal_id, command_name, surface_id)
        return Deny(reason="not on the list")


def _envelope(event: ActorRegistered | ActorDeactivated | ActorReactivated) -> NewEvent:
    return to_new_event(
        event_type=type(event).__name__,
        payload=to_payload(event),
        occurred_at=event.occurred_at,
        event_id=uuid4(),
        command_name="test",
        correlation_id=uuid4(),
        causation_id=None,
        principal_id=uuid4(),
    )


def _kernel(
    *, authz: object | None = None, event_store: InMemoryEventStore | None = None
) -> Kernel:
    return make_inmemory_kernel(
        settings=Settings(app_env="test"),
        clock=_FixedClock(),
        id_generator=_Uuid4Generator(),  # pyright: ignore[reportArgumentType]
        authz=authz or AllowAllAuthorize(),  # pyright: ignore[reportArgumentType]
        event_store=event_store or InMemoryEventStore(),
    )


async def _deactivated(store: InMemoryEventStore) -> UUID:
    """A registered actor that has since been switched off."""
    actor_id = uuid4()
    await store.append(
        ACTOR_STREAM_TYPE,
        actor_id,
        0,
        [_envelope(ActorRegistered(actor_id=actor_id, occurred_at=_WHEN))],
    )
    await store.append(
        ACTOR_STREAM_TYPE,
        actor_id,
        1,
        [_envelope(ActorDeactivated(actor_id=actor_id, occurred_at=_WHEN))],
    )
    return actor_id


async def test_reactivating_an_inactive_actor_folds_it_back_to_active() -> None:
    store = InMemoryEventStore()
    actor_id = await _deactivated(store)
    deps = _kernel(event_store=store)

    await bind(deps)(
        ReactivateActor(actor_id=actor_id), principal_id=uuid4(), correlation_id=uuid4()
    )

    assert await load_actor(store, actor_id) == Actor(id=actor_id, active=True)


async def test_the_full_cycle_leaves_every_switch_on_the_stream() -> None:
    """Three events, in order, for an actor that ends where it started.

    The state after a deactivation and a reactivation is the state it
    began in, so state alone cannot tell the cycle from a no-op. The
    stream can.
    """
    deps = _kernel()
    store = deps.event_store
    assert isinstance(store, InMemoryEventStore)
    actor_id = uuid4()
    await store.append(
        ACTOR_STREAM_TYPE,
        actor_id,
        0,
        [_envelope(ActorRegistered(actor_id=actor_id, occurred_at=_WHEN))],
    )
    caller, cid = uuid4(), uuid4()

    await bind_deactivate(deps)(
        DeactivateActor(actor_id=actor_id), principal_id=caller, correlation_id=cid
    )
    await bind(deps)(ReactivateActor(actor_id=actor_id), principal_id=caller, correlation_id=cid)

    rows, version = await store.load(ACTOR_STREAM_TYPE, actor_id)
    assert [row.event_type for row in rows] == [
        "ActorRegistered",
        "ActorDeactivated",
        "ActorReactivated",
    ]
    assert version == 3
    assert await load_actor(store, actor_id) == Actor(id=actor_id, active=True)


async def test_the_appended_event_records_the_principal_that_issued_the_command() -> None:
    store = InMemoryEventStore()
    actor_id = await _deactivated(store)
    deps = _kernel(event_store=store)
    caller = uuid4()

    await bind(deps)(
        ReactivateActor(actor_id=actor_id), principal_id=caller, correlation_id=uuid4()
    )

    rows, _version = await store.load(ACTOR_STREAM_TYPE, actor_id)
    assert rows[-1].principal_id == caller


async def test_reactivating_an_actor_that_was_never_registered_writes_nothing() -> None:
    deps = _kernel()
    store = deps.event_store
    assert isinstance(store, InMemoryEventStore)
    missing = uuid4()

    with pytest.raises(ActorNotFoundError):
        await bind(deps)(
            ReactivateActor(actor_id=missing), principal_id=uuid4(), correlation_id=uuid4()
        )

    _rows, version = await store.load(ACTOR_STREAM_TYPE, missing)
    assert version == 0


async def test_reactivating_the_same_actor_twice_is_refused_the_second_time() -> None:
    store = InMemoryEventStore()
    actor_id = await _deactivated(store)
    deps = _kernel(event_store=store)
    handler = bind(deps)

    await handler(ReactivateActor(actor_id=actor_id), principal_id=uuid4(), correlation_id=uuid4())
    with pytest.raises(ActorCannotBeReactivatedError):
        await handler(
            ReactivateActor(actor_id=actor_id), principal_id=uuid4(), correlation_id=uuid4()
        )

    _rows, version = await store.load(ACTOR_STREAM_TYPE, actor_id)
    assert version == 3, "the refused call must not have appended"


async def test_a_denied_caller_gets_an_error_and_writes_nothing() -> None:
    store = InMemoryEventStore()
    actor_id = await _deactivated(store)
    deps = _kernel(authz=_DenyAllAuthorize(), event_store=store)

    with pytest.raises(UnauthorizedError, match="not on the list"):
        await bind(deps)(
            ReactivateActor(actor_id=actor_id), principal_id=uuid4(), correlation_id=uuid4()
        )

    assert await load_actor(store, actor_id) == Actor(id=actor_id, active=False)


class _RecordingEventStore(InMemoryEventStore):
    """Remembers the `expected_version` each append was called with."""

    def __init__(self) -> None:
        super().__init__()
        self.appended_at: list[int] = []

    async def append(
        self,
        stream_type: str,
        stream_id: UUID,
        expected_version: int,
        events: Sequence[NewEvent],
    ) -> int:
        self.appended_at.append(expected_version)
        return await super().append(stream_type, stream_id, expected_version, events)


async def test_the_append_uses_the_version_the_load_returned() -> None:
    """Pins the plumbing, not just its effect. See the module docstring."""
    store = _RecordingEventStore()
    actor_id = await _deactivated(store)
    await store.append(
        ACTOR_STREAM_TYPE,
        actor_id,
        2,
        [_envelope(ActorReactivated(actor_id=actor_id, occurred_at=_WHEN))],
    )
    await store.append(
        ACTOR_STREAM_TYPE,
        actor_id,
        3,
        [_envelope(ActorDeactivated(actor_id=actor_id, occurred_at=_WHEN))],
    )
    _rows, version_before = await store.load(ACTOR_STREAM_TYPE, actor_id)
    assert version_before == 4

    deps = _kernel(event_store=store)
    await bind(deps)(
        ReactivateActor(actor_id=actor_id), principal_id=uuid4(), correlation_id=uuid4()
    )

    assert store.appended_at[-1] == version_before
