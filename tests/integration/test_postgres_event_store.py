"""The event store, against a real Postgres.

This adapter is the one piece of infrastructure whose bugs are
unrecoverable. Every other component can be rebuilt from the event log;
the event log cannot be rebuilt from anything.

Most of what it owes callers it owes jointly with the in-memory twin, so
those behaviours live in `tests/_port_contracts/event_store.py` and the
driver below runs them here. They used to live in this file, asserted
against Postgres alone, which left the twin that carries the entire unit
tier pinned by nothing at all.

What stays here is what only a database can show:

  - a unique violation on a reused event id arrives as the database's own
    error rather than as a concurrency refusal, so a generator bug does
    not enter the retry path. The shared contract asserts the part both
    adapters can keep, which is that it is not a `ConcurrencyError`; the
    narrower fact that it is asyncpg's own class is asserted here.
  - an append handed the caller's connection joins the caller's
    transaction, and dies with it
  - an append wakes a listener, so a projection does not sit out its
    poll interval
"""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false

import asyncio
from uuid import uuid4

import asyncpg
import pytest

from keeper.infrastructure.adapters.postgres_event_store import PostgresEventStore
from keeper.infrastructure.ports.event_store import StreamAppend
from tests._port_contracts.event_store import CHECKS, Check, an_event

pytestmark = [pytest.mark.integration]


@pytest.fixture
def store(db_pool: asyncpg.Pool) -> PostgresEventStore:
    return PostgresEventStore(db_pool)


@pytest.mark.parametrize("check", CHECKS, ids=lambda c: c.__name__)
async def test_the_postgres_event_store_keeps_the_port_contract(
    check: Check, store: PostgresEventStore
) -> None:
    await check(store)


async def test_a_duplicate_event_id_surfaces_as_the_databases_own_unique_violation(
    store: PostgresEventStore,
) -> None:
    """Two UNIQUE constraints can fire on one INSERT and they mean
    different things. Mapping a reused id onto `ConcurrencyError` would
    send the caller into a retry loop that reloads, re-appends the same
    id, and fails identically forever.
    """
    reused = uuid4()
    await store.append("thing", uuid4(), 0, [an_event(event_id=reused)])

    with pytest.raises(asyncpg.UniqueViolationError):
        await store.append("thing", uuid4(), 0, [an_event(event_id=reused)])


async def test_an_append_on_the_callers_connection_rolls_back_with_their_transaction(
    store: PostgresEventStore, db_pool: asyncpg.Pool
) -> None:
    """The `conn=` path exists so a slice can write a side table and append
    its event atomically. If the append did not join the caller's
    transaction, the two halves could diverge.
    """
    stream = uuid4()
    async with db_pool.acquire() as conn:
        transaction = conn.transaction()
        await transaction.start()
        await store.append_streams([StreamAppend("thing", stream, 0, [an_event()])], conn=conn)
        await transaction.rollback()

    assert await store.load("thing", stream) == ([], 0)


async def test_an_append_notifies_listeners_so_a_projection_wakes_promptly(
    store: PostgresEventStore, db_pool: asyncpg.Pool
) -> None:
    """The wake-up is a latency optimisation, not the source of truth, but
    a trigger that silently stopped firing would leave every projection
    running at the poll interval with nothing to say so.
    """
    received: asyncio.Queue[str] = asyncio.Queue()

    def _on_notify(_conn: object, _pid: int, _channel: str, payload: str) -> None:
        received.put_nowait(payload)

    async with db_pool.acquire() as listener:
        await listener.add_listener("events", _on_notify)
        try:
            await store.append("thing", uuid4(), 0, [an_event()])
            await asyncio.wait_for(received.get(), timeout=5.0)
        finally:
            # Same callable object, or asyncpg leaves the listener attached
            # and warns when the connection returns to the pool.
            await listener.remove_listener("events", _on_notify)
