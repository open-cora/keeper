"""The deactivation handler, against in-process stores.

The first update-style handler here: it loads and folds before deciding,
where the registering one hands `state=None` straight to the decider.
Two of these are about that difference.

Two are about the version. The racing one proves a stale fold loses its
append; the recording one proves the version written is the one read,
which the race cannot show because a constant equal to the real version
loses the race just the same.
"""

from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from keeper.access.aggregates.actor import (
    ACTOR_STREAM_TYPE,
    Actor,
    ActorCannotBeDeactivatedError,
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
from keeper.access.features.deactivate_actor import DeactivateActor, bind
from keeper.infrastructure.adapters.in_memory_event_store import InMemoryEventStore
from keeper.infrastructure.deps import make_inmemory_kernel
from keeper.infrastructure.kernel import Kernel
from keeper.infrastructure.ports import AllowAllAuthorize, ConcurrencyError, Deny
from keeper.infrastructure.ports.authorize import AuthzResult
from keeper.infrastructure.ports.event_store import NewEvent, StoredEvent
from keeper.infrastructure.settings import Settings
from keeper.infrastructure.slices.envelope import to_new_event
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


class _RacingEventStore(InMemoryEventStore):
    """Lands a competing append the first time a stream is read.

    Stands in for another request that got there first: the handler folds
    a state that is already stale by the time it tries to write.
    """

    def __init__(self) -> None:
        super().__init__()
        self.raced = False

    async def load(self, stream_type: str, stream_id: UUID) -> tuple[list[StoredEvent], int]:
        rows, version = await super().load(stream_type, stream_id)
        if not self.raced and version > 0:
            self.raced = True
            await super().append(
                stream_type,
                stream_id,
                version,
                [_envelope(ActorDeactivated(actor_id=stream_id, occurred_at=_WHEN))],
            )
        return rows, version


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


class _Uuid4Generator:
    def new_id(self) -> UUID:
        return uuid4()


async def _registered(store: InMemoryEventStore) -> UUID:
    """Put one registered actor on a stream and return its id."""
    actor_id = uuid4()
    await store.append(
        ACTOR_STREAM_TYPE,
        actor_id,
        0,
        [_envelope(ActorRegistered(actor_id=actor_id, occurred_at=_WHEN))],
    )
    return actor_id


async def test_deactivating_a_registered_actor_folds_it_to_inactive() -> None:
    deps = _kernel()
    store = deps.event_store
    assert isinstance(store, InMemoryEventStore)
    actor_id = await _registered(store)

    await bind(deps)(
        DeactivateActor(actor_id=actor_id), principal_id=uuid4(), correlation_id=uuid4()
    )

    assert await load_actor(store, actor_id) == Actor(id=actor_id, active=False)


async def test_deactivating_appends_onto_the_existing_stream_rather_than_a_new_one() -> None:
    """A handler passing version 0 would be refused here, not silently branch."""
    deps = _kernel()
    store = deps.event_store
    assert isinstance(store, InMemoryEventStore)
    actor_id = await _registered(store)

    await bind(deps)(
        DeactivateActor(actor_id=actor_id), principal_id=uuid4(), correlation_id=uuid4()
    )

    rows, version = await store.load(ACTOR_STREAM_TYPE, actor_id)
    assert version == 2
    assert [row.event_type for row in rows] == ["ActorRegistered", "ActorDeactivated"]


async def test_the_appended_event_records_the_principal_that_issued_the_command() -> None:
    deps = _kernel()
    store = deps.event_store
    assert isinstance(store, InMemoryEventStore)
    actor_id = await _registered(store)
    caller = uuid4()

    await bind(deps)(
        DeactivateActor(actor_id=actor_id), principal_id=caller, correlation_id=uuid4()
    )

    rows, _version = await store.load(ACTOR_STREAM_TYPE, actor_id)
    assert rows[-1].principal_id == caller


async def test_deactivating_an_actor_that_was_never_registered_writes_nothing() -> None:
    deps = _kernel()
    store = deps.event_store
    assert isinstance(store, InMemoryEventStore)
    missing = uuid4()

    with pytest.raises(ActorNotFoundError):
        await bind(deps)(
            DeactivateActor(actor_id=missing), principal_id=uuid4(), correlation_id=uuid4()
        )

    _rows, version = await store.load(ACTOR_STREAM_TYPE, missing)
    assert version == 0


async def test_deactivating_the_same_actor_twice_is_refused_the_second_time() -> None:
    deps = _kernel()
    store = deps.event_store
    assert isinstance(store, InMemoryEventStore)
    actor_id = await _registered(store)
    handler = bind(deps)

    await handler(DeactivateActor(actor_id=actor_id), principal_id=uuid4(), correlation_id=uuid4())
    with pytest.raises(ActorCannotBeDeactivatedError):
        await handler(
            DeactivateActor(actor_id=actor_id), principal_id=uuid4(), correlation_id=uuid4()
        )

    _rows, version = await store.load(ACTOR_STREAM_TYPE, actor_id)
    assert version == 2, "the refused call must not have appended"


async def test_a_denied_caller_gets_an_error_and_writes_nothing() -> None:
    store = InMemoryEventStore()
    actor_id = await _registered(store)
    deps = _kernel(authz=_DenyAllAuthorize(), event_store=store)

    with pytest.raises(UnauthorizedError, match="not on the list"):
        await bind(deps)(
            DeactivateActor(actor_id=actor_id), principal_id=uuid4(), correlation_id=uuid4()
        )

    assert await load_actor(store, actor_id) == Actor(id=actor_id, active=True)


async def test_a_write_that_lands_between_the_read_and_the_append_is_refused() -> None:
    """A handler holding a stale fold must lose the append, not win it.

    The racing store moves the stream after the handler has read it. A
    handler that re-read the version just before appending would write
    on top of the competing event; passing the version it folded from
    makes the store refuse.

    This does NOT distinguish the read version from a constant that
    happens to equal it. `test_the_append_uses_the_version_the_load_
    returned` is the one that does.
    """
    store = _RacingEventStore()
    actor_id = await _registered(store)
    deps = _kernel(event_store=store)

    with pytest.raises(ConcurrencyError):
        await bind(deps)(
            DeactivateActor(actor_id=actor_id), principal_id=uuid4(), correlation_id=uuid4()
        )

    assert store.raced, "the racing store never injected a competing write"
    _rows, version = await store.load(ACTOR_STREAM_TYPE, actor_id)
    assert version == 2, "only the competing write should have landed"


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
    """Pins the plumbing, not just its effect.

    Every other path here runs against a stream sitting at version 1,
    where a handler passing the constant 1 behaves identically to one
    passing what it read. This executions the actor off and on again first,
    leaving it active at version 3, so the two come apart.
    """
    store = _RecordingEventStore()
    actor_id = await _registered(store)
    await store.append(
        ACTOR_STREAM_TYPE,
        actor_id,
        1,
        [_envelope(ActorDeactivated(actor_id=actor_id, occurred_at=_WHEN))],
    )
    await store.append(
        ACTOR_STREAM_TYPE,
        actor_id,
        2,
        [_envelope(ActorReactivated(actor_id=actor_id, occurred_at=_WHEN))],
    )
    _rows, version_before = await store.load(ACTOR_STREAM_TYPE, actor_id)
    assert version_before == 3

    deps = _kernel(event_store=store)
    await bind(deps)(
        DeactivateActor(actor_id=actor_id), principal_id=uuid4(), correlation_id=uuid4()
    )

    assert store.appended_at[-1] == version_before
