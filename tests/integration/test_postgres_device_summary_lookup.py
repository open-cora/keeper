"""The device projection and its query, against a real Postgres.

The other side of the device-summary contract. The files beside this one
carry the shared reasoning about draining, replay and lag; what is here
is this projection's own.

Two things are its own. The status is derived a second time here, by the
projection's map rather than by the fold, and the shared contract is
what makes those two agree; this driver is the half that exercises the
map. And the update arm is reached by three different event types rather
than one, so a replayed batch has three ways to land somewhere other
than where the first pass left it.
"""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import asyncpg
import pytest

from keeper.equipment.adapters.postgres_device_summary_lookup import (
    PostgresDeviceSummaryLookup,
)
from keeper.equipment.aggregates.device import DEVICE_STREAM_TYPE, DeviceFaulted
from keeper.equipment.aggregates.device import to_payload as device_payload
from keeper.equipment.projections.device_summary import DeviceSummaryProjection
from keeper.infrastructure.adapters.postgres_event_store import PostgresEventStore
from keeper.infrastructure.projection.worker import advance_subscriber_once
from keeper.infrastructure.slices.envelope import to_new_event
from keeper.shared.identifier import Identifier
from tests._port_contracts._writers import EventStoreDeviceWriter
from tests._port_contracts.device_summary_lookup import CHECKS, Check

pytestmark = [pytest.mark.integration]

_WHEN = datetime(2026, 3, 1, 9, 0, tzinfo=UTC)
_REF = Identifier(scheme="example-control", value="station-1:m1")


class _DrainingDeviceWriter:
    """Append device events, then let the projection catch up."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool
        self._writer = EventStoreDeviceWriter(PostgresEventStore(pool))
        self._projection = DeviceSummaryProjection()

    async def register(
        self,
        *,
        device_id: UUID,
        external_ref: Identifier,
        device_name: str,
        at: datetime,
    ) -> None:
        await self._writer.register(
            device_id=device_id,
            external_ref=external_ref,
            device_name=device_name,
            at=at,
        )
        await self._drain()

    async def fault(self, *, device_id: UUID, at: datetime) -> None:
        await self._writer.fault(device_id=device_id, at=at)
        await self._drain()

    async def recover(self, *, device_id: UUID, at: datetime) -> None:
        await self._writer.recover(device_id=device_id, at=at)
        await self._drain()

    async def retire(self, *, device_id: UUID, at: datetime) -> None:
        await self._writer.retire(device_id=device_id, at=at)
        await self._drain()

    async def _drain(self) -> None:
        while await advance_subscriber_once(self._pool, self._projection):
            pass


@pytest.fixture
def lookup(db_pool: asyncpg.Pool) -> PostgresDeviceSummaryLookup:
    return PostgresDeviceSummaryLookup(db_pool)


@pytest.fixture
def writer(db_pool: asyncpg.Pool) -> _DrainingDeviceWriter:
    return _DrainingDeviceWriter(db_pool)


@pytest.mark.parametrize("check", CHECKS, ids=lambda c: c.__name__)
async def test_the_postgres_device_summary_lookup_keeps_the_port_contract(
    check: Check, lookup: PostgresDeviceSummaryLookup, writer: _DrainingDeviceWriter
) -> None:
    await check(lookup, writer)


async def test_the_migration_seeded_the_bookmark_this_projection_reads(
    db_pool: asyncpg.Pool,
) -> None:
    """Without the row the worker raises on its first advance, forever,
    inside its own backoff loop."""
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT last_position FROM projection_bookmarks WHERE name = $1",
            DeviceSummaryProjection.name,
        )
    assert row is not None
    assert row["last_position"] == 0


async def test_a_device_event_does_not_move_another_contexts_bookmark(
    db_pool: asyncpg.Pool, lookup: PostgresDeviceSummaryLookup
) -> None:
    """Six projections now tail one log across five contexts. Each has its
    own bookmark and its own subscription, so a device landing does not
    advance Execution's cursors past events they have not seen."""
    await EventStoreDeviceWriter(PostgresEventStore(db_pool)).register(
        device_id=uuid4(), external_ref=_REF, device_name="a device", at=_WHEN
    )

    assert await advance_subscriber_once(db_pool, DeviceSummaryProjection()) == 1

    async with db_pool.acquire() as conn:
        execution_bookmark = await conn.fetchval(
            "SELECT last_position FROM projection_bookmarks WHERE name = $1",
            "proj_execution_execution_summary",
        )
    assert execution_bookmark == 0
    assert (
        len(
            (await lookup.list_devices(external_ref=None, status=None, limit=10, cursor=None)).items
        )
        == 1
    )


async def test_replaying_a_batch_of_every_event_leaves_the_table_as_it_was(
    db_pool: asyncpg.Pool, lookup: PostgresDeviceSummaryLookup
) -> None:
    """Delivery is at-least-once, and this projection replays three UPDATE
    paths as well as an INSERT. The insert has `ON CONFLICT`; the updates
    have only the fact that each writes the event's own values rather than
    reading the row first, which is what makes a second pass a no-op.

    The device is walked through every transition so the replay covers all
    three arms rather than whichever one a shorter test picked.
    """
    writer = _DrainingDeviceWriter(db_pool)
    device_id = uuid4()
    await writer.register(device_id=device_id, external_ref=_REF, device_name="a device", at=_WHEN)
    await writer.fault(device_id=device_id, at=_WHEN + timedelta(minutes=1))
    await writer.recover(device_id=device_id, at=_WHEN + timedelta(minutes=2))
    await writer.retire(device_id=device_id, at=_WHEN + timedelta(minutes=3))
    first = await lookup.list_devices(external_ref=None, status=None, limit=10, cursor=None)

    async with db_pool.acquire() as conn:
        await conn.execute(
            "UPDATE projection_bookmarks SET last_transaction_id = '0'::xid8, "
            "last_position = 0 WHERE name = $1",
            DeviceSummaryProjection.name,
        )
    while await advance_subscriber_once(db_pool, DeviceSummaryProjection()):
        pass

    assert (
        await lookup.list_devices(external_ref=None, status=None, limit=10, cursor=None)
    ) == first


async def test_a_fault_arriving_before_its_genesis_does_not_wedge_the_projection(
    db_pool: asyncpg.Pool, lookup: PostgresDeviceSummaryLookup
) -> None:
    """The ordering guarantee says this cannot happen, so the arm logs
    rather than raises. What is pinned here is that choice: a raise would
    roll the batch back forever and stop every later device appearing,
    which is a worse failure than one row missing.

    The event is appended by hand at version 0, because the writer's
    `fault` appends after a registration and so cannot produce the orphan
    this is about.
    """
    orphan = uuid4()
    faulted = DeviceFaulted(device_id=orphan, occurred_at=_WHEN)
    await PostgresEventStore(db_pool).append(
        DEVICE_STREAM_TYPE,
        orphan,
        0,
        [
            to_new_event(
                event_type="DeviceFaulted",
                payload=device_payload(faulted),
                occurred_at=_WHEN,
                event_id=uuid4(),
                command_name="FaultDevice",
                correlation_id=uuid4(),
                principal_id=uuid4(),
            )
        ],
    )
    later = uuid4()
    await EventStoreDeviceWriter(PostgresEventStore(db_pool)).register(
        device_id=later, external_ref=_REF, device_name="a device", at=_WHEN
    )

    while await advance_subscriber_once(db_pool, DeviceSummaryProjection()):
        pass

    page = await lookup.list_devices(external_ref=None, status=None, limit=10, cursor=None)
    found = {summary.device_id for summary in page.items}
    assert later in found, "the projection carried on past the orphan"
    assert orphan not in found, "an update with no row writes nothing"
