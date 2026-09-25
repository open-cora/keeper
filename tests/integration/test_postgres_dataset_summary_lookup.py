"""The dataset projection and its query, against a real Postgres.

The other side of the dataset-summary contract. The two files beside this
one carry the shared reasoning about draining, replay and lag; what is
here is this projection's own, and it is the simplest of the three: one
subscribed event type, one insert, no update and no derived status.

That simplicity is worth a test rather than a shrug. A projection with no
update arm cannot corrupt a column on replay, which is the hazard the run
projection has to keep in mind, so the replay check below is pinning that
the `ON CONFLICT` is doing the work rather than luck.
"""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false

from datetime import UTC, datetime
from uuid import UUID, uuid4

import asyncpg
import pytest

from keeper.custody.adapters.postgres_dataset_summary_lookup import (
    PostgresDatasetSummaryLookup,
)
from keeper.custody.projections.dataset_summary import DatasetSummaryProjection
from keeper.infrastructure.adapters.postgres_event_store import PostgresEventStore
from keeper.infrastructure.projection.worker import advance_subscriber_once
from keeper.shared.identifier import Identifier
from tests._port_contracts._writers import EventStoreDatasetWriter
from tests._port_contracts.dataset_summary_lookup import CHECKS, Check

pytestmark = [pytest.mark.integration]


class _DrainingDatasetWriter:
    """Append dataset events, then let the projection catch up."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool
        self._writer = EventStoreDatasetWriter(PostgresEventStore(pool))
        self._projection = DatasetSummaryProjection()

    async def register(
        self,
        *,
        dataset_id: UUID,
        execution_id: UUID,
        step_id: UUID,
        external_ref: Identifier,
        at: datetime,
    ) -> None:
        await self._writer.register(
            dataset_id=dataset_id,
            execution_id=execution_id,
            step_id=step_id,
            external_ref=external_ref,
            at=at,
        )
        while await advance_subscriber_once(self._pool, self._projection):
            pass


@pytest.fixture
def lookup(db_pool: asyncpg.Pool) -> PostgresDatasetSummaryLookup:
    return PostgresDatasetSummaryLookup(db_pool)


@pytest.fixture
def writer(db_pool: asyncpg.Pool) -> _DrainingDatasetWriter:
    return _DrainingDatasetWriter(db_pool)


@pytest.mark.parametrize("check", CHECKS, ids=lambda c: c.__name__)
async def test_the_postgres_dataset_summary_lookup_keeps_the_port_contract(
    check: Check, lookup: PostgresDatasetSummaryLookup, writer: _DrainingDatasetWriter
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
            DatasetSummaryProjection.name,
        )
    assert row is not None
    assert row["last_position"] == 0


async def test_a_dataset_event_does_not_move_another_contexts_bookmark(
    db_pool: asyncpg.Pool, lookup: PostgresDatasetSummaryLookup
) -> None:
    """Three projections now tail one log, and the third crosses a
    bounded-context boundary. Each has its own bookmark and its own
    subscription, so a dataset landing does not advance Execution's
    cursors past events they have not seen."""
    writer = EventStoreDatasetWriter(PostgresEventStore(db_pool))
    await writer.register(
        dataset_id=uuid4(),
        execution_id=uuid4(),
        step_id=uuid4(),
        external_ref=Identifier(scheme="example-store-path", value="raw/one"),
        at=datetime.now(tz=UTC),
    )

    assert await advance_subscriber_once(db_pool, DatasetSummaryProjection()) == 1

    async with db_pool.acquire() as conn:
        execution_bookmark = await conn.fetchval(
            "SELECT last_position FROM projection_bookmarks WHERE name = $1",
            "proj_execution_execution_summary",
        )
    assert execution_bookmark == 0
    assert len((await lookup.list_datasets(step_id=None, limit=10, cursor=None)).items) == 1


async def test_replaying_a_batch_leaves_the_table_exactly_as_it_was(
    db_pool: asyncpg.Pool, lookup: PostgresDatasetSummaryLookup
) -> None:
    """Delivery is at-least-once, and the insert's ON CONFLICT is the only
    thing standing between a replay and a duplicate-key failure that would
    wedge the projection for good."""
    writer = _DrainingDatasetWriter(db_pool)
    await writer.register(
        dataset_id=uuid4(),
        execution_id=uuid4(),
        step_id=uuid4(),
        external_ref=Identifier(scheme="example-store-path", value="raw/one"),
        at=datetime.now(tz=UTC),
    )
    first = await lookup.list_datasets(step_id=None, limit=10, cursor=None)

    async with db_pool.acquire() as conn:
        await conn.execute(
            "UPDATE projection_bookmarks SET last_transaction_id = '0'::xid8, "
            "last_position = 0 WHERE name = $1",
            DatasetSummaryProjection.name,
        )
    while await advance_subscriber_once(db_pool, DatasetSummaryProjection()):
        pass

    assert await lookup.list_datasets(step_id=None, limit=10, cursor=None) == first
