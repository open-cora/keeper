"""The Access slices, driven end to end against a real Postgres.

Every other test of this bounded context runs on `InMemoryEventStore`,
which is a dict behind a lock. It answers a different question from the
one the deployed system asks. Four things can only be learned here:

  - the payload survives a round trip through JSONB and comes back as
    the same event, rather than as a dict that merely looks similar
  - the envelope lands in COLUMNS, so a handler that forgot to pass the
    principal writes a NULL rather than an object nobody inspected
  - a concurrent writer is refused by a UNIQUE constraint, which is a
    different mechanism from the in-memory lock and fails differently
  - the idempotency claim is one SQL round trip with an ON CONFLICT
    clause, and nothing has ever run it against real SQL

Two of the queries below spell `"Actor"` as a literal rather than using
`ACTOR_STREAM_TYPE`. That is the only independent side these tests have:
a query built from the writer's own constant agrees with the writer
however wrong the constant is.

The handlers come from `wire_access`, not from `bind`, so these go
through the same composition the application boots: tracing, and for
registering, the idempotency wrapper.
"""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false

import asyncio
import json
from uuid import UUID, uuid4

import asyncpg
import pytest

from keeper.access import wire_access
from keeper.access.aggregates.actor import (
    ACTOR_STREAM_TYPE,
    Actor,
    ActorCannotBeDeactivatedError,
    load_actor,
)
from keeper.access.features.deactivate_actor import DeactivateActor
from keeper.access.features.get_actor import GetActor
from keeper.access.features.reactivate_actor import ReactivateActor
from keeper.access.features.register_actor import RegisterActor
from keeper.access.wire import AccessHandlers
from keeper.infrastructure.adapters.postgres_event_store import PostgresEventStore
from keeper.infrastructure.deps import make_postgres_kernel
from keeper.infrastructure.ports import ConcurrencyError
from keeper.infrastructure.ports.authorize import AllowAllAuthorize
from keeper.infrastructure.ports.clock import SystemClock
from keeper.infrastructure.ports.id_generator import UUIDv7Generator
from keeper.infrastructure.settings import Settings

pytestmark = [pytest.mark.integration]


@pytest.fixture
def handlers(db_pool: asyncpg.Pool) -> AccessHandlers:
    """The Access bundle, wired exactly as the application wires it."""
    return wire_access(
        make_postgres_kernel(
            db_pool,
            settings=Settings(app_env="test"),
            clock=SystemClock(),
            id_generator=UUIDv7Generator(),
            authz=AllowAllAuthorize(),
        )
    )


async def _register(handlers: AccessHandlers, *, principal: UUID | None = None) -> UUID:
    return await handlers.register_actor(
        RegisterActor(), principal_id=principal or uuid4(), correlation_id=uuid4()
    )


async def test_the_whole_lifecycle_survives_a_round_trip_through_postgres(
    handlers: AccessHandlers, db_pool: asyncpg.Pool
) -> None:
    """Register, switch off, switch on, and read the answer back out of SQL.

    The in-memory store hands back the very objects it was given. Here
    each event is serialised to JSONB, written, read, and rebuilt, so a
    field that does not survive that trip shows up as a fold that
    disagrees with the one the unit tests saw.
    """
    actor_id = await _register(handlers)
    caller, cid = uuid4(), uuid4()

    await handlers.deactivate_actor(
        DeactivateActor(actor_id=actor_id), principal_id=caller, correlation_id=cid
    )
    await handlers.reactivate_actor(
        ReactivateActor(actor_id=actor_id), principal_id=caller, correlation_id=cid
    )

    rows = await db_pool.fetch(
        "SELECT event_type FROM events WHERE stream_type = $1 AND stream_id = $2 ORDER BY version",
        ACTOR_STREAM_TYPE,
        actor_id,
    )
    assert [r["event_type"] for r in rows] == [
        "ActorRegistered",
        "ActorDeactivated",
        "ActorReactivated",
    ]

    actor = await handlers.get_actor(
        GetActor(actor_id=actor_id), principal_id=caller, correlation_id=cid
    )
    assert actor == Actor(id=actor_id, active=True)


async def test_the_stored_row_carries_the_envelope_in_its_own_columns(
    handlers: AccessHandlers, db_pool: asyncpg.Pool
) -> None:
    """Who asked, and under what correlation, are columns rather than payload.

    A handler that dropped either would still produce a readable actor,
    and the loss would only appear when somebody tried to audit it.
    """
    caller, cid = uuid4(), uuid4()
    actor_id = await handlers.register_actor(
        RegisterActor(), principal_id=caller, correlation_id=cid
    )

    row = await db_pool.fetchrow(
        "SELECT principal_id, correlation_id, stream_type, payload, metadata "
        "FROM events WHERE stream_id = $1",
        actor_id,
    )
    assert row is not None
    assert row["principal_id"] == caller
    assert row["correlation_id"] == cid
    assert row["stream_type"] == ACTOR_STREAM_TYPE


async def test_the_stored_payload_holds_only_an_id_and_a_timestamp(
    handlers: AccessHandlers, db_pool: asyncpg.Pool
) -> None:
    """The personal-data boundary, read back off the disk it landed on.

    The architecture rule reads the source; the unit test reads the
    dict the builder returned. This reads the column, which is the only
    one of the three that is what a regulator would be shown.
    """
    actor_id = await _register(handlers)

    # `payload::text` rather than `payload`: the pool registers a JSONB
    # codec, so the plain column comes back already decoded. Reading the
    # text is reading what the column holds.
    stored = await db_pool.fetchval(
        "SELECT payload::text FROM events WHERE stream_id = $1", actor_id
    )
    assert sorted(json.loads(stored)) == ["actor_id", "occurred_at"]


async def test_two_concurrent_deactivations_leave_one_winner(
    handlers: AccessHandlers, db_pool: asyncpg.Pool
) -> None:
    """The UNIQUE constraint decides, not a Python lock.

    Both callers fold the same active actor and both try to append at
    the same version. In memory a lock serialises them; here the second
    INSERT violates events_stream_version_unique and the adapter turns
    that into ConcurrencyError. One event, one error, never two events.
    """
    actor_id = await _register(handlers)

    results = await asyncio.gather(
        *(
            handlers.deactivate_actor(
                DeactivateActor(actor_id=actor_id),
                principal_id=uuid4(),
                correlation_id=uuid4(),
            )
            for _ in range(2)
        ),
        return_exceptions=True,
    )

    failures = [r for r in results if isinstance(r, BaseException)]
    assert len(failures) == 1, f"expected exactly one loser, got {results}"
    assert isinstance(failures[0], ConcurrencyError | ActorCannotBeDeactivatedError)

    count = await db_pool.fetchval(
        "SELECT count(*) FROM events WHERE stream_id = $1 AND event_type = 'ActorDeactivated'",
        actor_id,
    )
    assert count == 1


async def test_a_stale_writer_is_refused_rather_than_appended_after_the_winner(
    handlers: AccessHandlers, db_pool: asyncpg.Pool
) -> None:
    """A second deactivation of an actor already switched off writes nothing.

    Sequential rather than concurrent, so the refusal comes from the
    decider rather than the constraint. Both paths must leave the stream
    at the same length, and only the database can confirm the second one
    did not quietly land.
    """
    actor_id = await _register(handlers)
    await handlers.deactivate_actor(
        DeactivateActor(actor_id=actor_id), principal_id=uuid4(), correlation_id=uuid4()
    )

    with pytest.raises(ActorCannotBeDeactivatedError):
        await handlers.deactivate_actor(
            DeactivateActor(actor_id=actor_id), principal_id=uuid4(), correlation_id=uuid4()
        )

    count = await db_pool.fetchval("SELECT count(*) FROM events WHERE stream_id = $1", actor_id)
    assert count == 2


async def test_replaying_an_idempotency_key_returns_the_first_actor_from_the_cache(
    handlers: AccessHandlers, db_pool: asyncpg.Pool
) -> None:
    """The two-phase claim, against the SQL that implements it.

    `claim()` is one round trip with an ON CONFLICT clause, and every
    other test of it uses a dict. A second call under the same key must
    return the first actor and append nothing, so the cache hit is
    visible as an event count of one across two requests.
    """
    caller = uuid4()
    key = "a-client-supplied-retry-tag"

    first = await handlers.register_actor(
        RegisterActor(), principal_id=caller, correlation_id=uuid4(), idempotency_key=key
    )
    second = await handlers.register_actor(
        RegisterActor(), principal_id=caller, correlation_id=uuid4(), idempotency_key=key
    )

    assert second == first
    # The literal "Actor", not ACTOR_STREAM_TYPE. Deliberate: a query
    # built from the same constant the writer used agrees with it by
    # construction, and would keep agreeing if the constant changed
    # under both. Spelling it out is the only independent side this
    # test has. Do not tidy it into the constant.
    total = await db_pool.fetchval("SELECT count(*) FROM events WHERE stream_type = $1", "Actor")
    assert total == 1, "the replay created a second actor"


async def test_the_same_key_under_a_different_principal_creates_its_own_actor(
    handlers: AccessHandlers, db_pool: asyncpg.Pool
) -> None:
    """The cache key is (principal, key, surface), enforced by the PRIMARY KEY.

    Two callers using the same retry tag are not retrying each other's
    request. Here that is a composite primary key rather than a tuple in
    a dict, and getting it wrong would hand one caller another's actor.
    """
    key = "the-same-tag"

    first = await handlers.register_actor(
        RegisterActor(), principal_id=uuid4(), correlation_id=uuid4(), idempotency_key=key
    )
    second = await handlers.register_actor(
        RegisterActor(), principal_id=uuid4(), correlation_id=uuid4(), idempotency_key=key
    )

    assert first != second
    total = await db_pool.fetchval("SELECT count(*) FROM events WHERE stream_type = $1", "Actor")
    assert total == 2


async def test_an_actor_reads_back_after_a_fresh_load_from_disk(
    handlers: AccessHandlers, db_pool: asyncpg.Pool
) -> None:
    """Fold the stream through the aggregate's own reader, not the handler.

    The handler could be caching. This goes to `load_actor` with a pool
    the handler never touched, so the answer comes from rows and nothing
    else.
    """
    actor_id = await _register(handlers)
    await handlers.deactivate_actor(
        DeactivateActor(actor_id=actor_id), principal_id=uuid4(), correlation_id=uuid4()
    )

    assert await load_actor(PostgresEventStore(db_pool), actor_id) == Actor(
        id=actor_id, active=False
    )
