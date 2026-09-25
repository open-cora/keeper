"""The append-only guarantee, observed rather than asserted.

`tests/architecture/test_migration_grants.py` checks that the migration TEXT
carries the REVOKE. That is the weaker half: a REVOKE can be present and
ineffective, and a text check would pass either way.

This is the other half. It connects AS the application role and watches
Postgres refuse. The positive control matters as much as the three refusals:
a role that could do nothing at all would produce the same three errors, so
without an INSERT that SUCCEEDS the test would pass against a completely
broken grant.
"""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false

from datetime import UTC, datetime
from uuid import uuid4

import asyncpg
import pytest

from tests.integration.conftest import ClonedDatabase

pytestmark = [pytest.mark.integration]

APP_ROLE = "keeper_app"

_INSERT = """
INSERT INTO events (
    event_id, stream_type, stream_id, version, event_type,
    payload, correlation_id, occurred_at
) VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7, $8)
"""


async def _app_role_connection(database: ClonedDatabase) -> asyncpg.Connection:
    """Connect to the test database as the unprivileged application role.

    The pool connects as the database OWNER, the role migrations run as, which
    is deliberately allowed to mutate anything. Reusing it here would test
    nothing at all.
    """
    return await asyncpg.connect(database.url_as(APP_ROLE, APP_ROLE))


async def _seed_one_event(conn: asyncpg.Connection) -> None:
    await conn.execute(
        _INSERT,
        uuid4(),
        "Thing",
        uuid4(),
        1,
        "ThingRegistered",
        "{}",
        uuid4(),
        datetime.now(UTC),
    )


async def test_app_role_can_insert_an_event(cloned_database: ClonedDatabase) -> None:
    """The positive control. Without it, the refusals below prove nothing."""
    conn = await _app_role_connection(cloned_database)
    try:
        await _seed_one_event(conn)
        count = await conn.fetchval("SELECT count(*) FROM events")
        assert count == 1
    finally:
        await conn.close()


@pytest.mark.parametrize(
    "statement",
    [
        pytest.param("UPDATE events SET payload = '{}'::jsonb", id="update"),
        pytest.param("DELETE FROM events", id="delete"),
        pytest.param("TRUNCATE events", id="truncate"),
    ],
)
async def test_app_role_is_refused_every_mutation_of_events(
    cloned_database: ClonedDatabase, statement: str
) -> None:
    conn = await _app_role_connection(cloned_database)
    try:
        await _seed_one_event(conn)
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await conn.execute(statement)
    finally:
        await conn.close()


async def test_duplicate_stream_version_is_refused_by_the_concurrency_key(
    cloned_database: ClonedDatabase,
) -> None:
    """Two writers at the same version must collide, not interleave.

    This is the optimistic-concurrency guarantee the whole append path rests
    on: a handler that folded state at version N appends at N+1, and a
    concurrent handler that folded the same state must fail rather than
    produce a stream with two different version N+1 events.
    """
    conn = await _app_role_connection(cloned_database)
    try:
        stream_id = uuid4()
        for _ in range(2):
            insert = conn.execute(
                _INSERT,
                uuid4(),
                "Thing",
                stream_id,
                1,
                "ThingRegistered",
                "{}",
                uuid4(),
                datetime.now(UTC),
            )
            if _ == 0:
                await insert
            else:
                with pytest.raises(asyncpg.UniqueViolationError):
                    await insert
    finally:
        await conn.close()
