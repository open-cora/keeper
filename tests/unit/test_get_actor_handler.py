"""The read handler, against in-process stores.

No decider, no append, no clock: a read produces no events. What is left
to check is that it authorizes before answering, that it folds the whole
stream rather than the first row of it, and that a missing actor is a
refusal rather than a null.

`test_a_denied_caller_learns_nothing_about_whether_the_actor_exists` is
the one worth reading. A read that checked existence first would answer
404 for an actor a caller may not see and 403 for one it may, which is
an existence oracle for anyone willing to read status codes.
"""

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from keeper.access.aggregates.actor import ACTOR_STREAM_TYPE, Actor, ActorNotFoundError, to_payload
from keeper.access.aggregates.actor.events import (
    ActorDeactivated,
    ActorReactivated,
    ActorRegistered,
)
from keeper.access.errors import UnauthorizedError
from keeper.access.features.get_actor import GetActor, bind
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
    def __init__(self) -> None:
        self.asked: list[str] = []

    async def authorize(
        self,
        principal_id: UUID,
        command_name: str,
        surface_id: UUID = NIL_SENTINEL_ID,
    ) -> AuthzResult:
        _ = (principal_id, surface_id)
        self.asked.append(command_name)
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


async def _stream(
    store: InMemoryEventStore,
    *event_types: type[ActorRegistered] | type[ActorDeactivated] | type[ActorReactivated],
) -> UUID:
    """Lay one event of each given type onto a fresh actor's stream, in order.

    Takes the classes rather than instances so every event carries the
    stream's own id. Building them outside would let an event's
    `actor_id` differ from the stream it lands on, which no handler can
    produce and which quietly makes the folded id meaningless.
    """
    actor_id = uuid4()
    for version, event_type in enumerate(event_types):
        await store.append(
            ACTOR_STREAM_TYPE,
            actor_id,
            version,
            [_envelope(event_type(actor_id=actor_id, occurred_at=_WHEN))],
        )
    return actor_id


async def test_reading_a_registered_actor_returns_it_active() -> None:
    store = InMemoryEventStore()
    actor_id = await _stream(store, ActorRegistered)
    deps = _kernel(event_store=store)

    actor = await bind(deps)(
        GetActor(actor_id=actor_id), principal_id=uuid4(), correlation_id=uuid4()
    )

    assert actor == Actor(id=actor_id, active=True)


async def test_reading_folds_the_whole_stream_and_not_a_single_row() -> None:
    """Four events, and only the fold gets the answer right.

    The first row says active and the last says inactive, so a handler
    reading either end alone is wrong about one of them. The middle
    reactivation is there so that a handler reading the last row is
    right for the wrong reason on a shorter stream.
    """
    store = InMemoryEventStore()
    actor_id = await _stream(
        store, ActorRegistered, ActorDeactivated, ActorReactivated, ActorDeactivated
    )
    deps = _kernel(event_store=store)

    actor = await bind(deps)(
        GetActor(actor_id=actor_id), principal_id=uuid4(), correlation_id=uuid4()
    )

    assert actor == Actor(id=actor_id, active=False)


async def test_reading_an_actor_that_was_never_registered_is_refused() -> None:
    deps = _kernel()

    with pytest.raises(ActorNotFoundError):
        await bind(deps)(GetActor(actor_id=uuid4()), principal_id=uuid4(), correlation_id=uuid4())


async def test_a_denied_caller_learns_nothing_about_whether_the_actor_exists() -> None:
    """Both a real id and an invented one give the same refusal.

    Authorization runs before the load, so the two cases cannot be told
    apart from outside. Moving the existence check ahead of the check
    turns status codes into an existence oracle.
    """
    store = InMemoryEventStore()
    real = await _stream(store, ActorRegistered)
    deps = _kernel(authz=_DenyAllAuthorize(), event_store=store)
    handler = bind(deps)

    for actor_id in (real, uuid4()):
        with pytest.raises(UnauthorizedError, match="not on the list"):
            await handler(GetActor(actor_id=actor_id), principal_id=uuid4(), correlation_id=uuid4())


async def test_the_read_asks_authorization_under_its_own_command_name() -> None:
    """A read borrowing a writing slice's label would be granted with it."""
    authz = _DenyAllAuthorize()
    deps = _kernel(authz=authz)

    with pytest.raises(UnauthorizedError):
        await bind(deps)(GetActor(actor_id=uuid4()), principal_id=uuid4(), correlation_id=uuid4())

    assert authz.asked == ["GetActor"]


async def test_reading_writes_nothing_to_the_stream() -> None:
    store = InMemoryEventStore()
    actor_id = await _stream(store, ActorRegistered)
    deps = _kernel(event_store=store)

    await bind(deps)(GetActor(actor_id=actor_id), principal_id=uuid4(), correlation_id=uuid4())

    _rows, version = await store.load(ACTOR_STREAM_TYPE, actor_id)
    assert version == 1
