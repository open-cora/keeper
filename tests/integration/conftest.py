"""Integration-tier fixtures: a per-test Postgres database.

`db_pool` clones the migrated template with `CREATE DATABASE ... TEMPLATE`,
which Postgres satisfies by file copy. Full isolation per test, no TRUNCATE
bookkeeping, and no ordering coupling between tests.

The session-scoped container and template fixtures live in `tests/conftest.py`
so the e2e tier shares them.
"""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false

from collections.abc import AsyncGenerator
from dataclasses import dataclass
from urllib.parse import urlparse, urlunparse
from uuid import uuid4

import asyncpg
import pytest_asyncio
from testcontainers.postgres import PostgresContainer

from keeper.infrastructure.pool import create_pool
from tests._postgres import normalize_async_url


@dataclass(frozen=True)
class ClonedDatabase:
    """A per-test database, plus the URL needed to reach it as another role.

    Named `ClonedDatabase` rather than `TestDatabase` because pytest collects
    any class whose name starts with `Test` and then warns that it cannot,
    since this one has a constructor.

    `pool` connects as the database OWNER, which is the role migrations run as
    and which is deliberately allowed to mutate anything. A test that wants to
    observe what the APPLICATION role can do must reconnect, so the URL is
    exposed rather than dug out of the pool's private attributes.
    """

    pool: asyncpg.Pool
    url: str

    def url_as(self, user: str, password: str) -> str:
        """The same database, reached as a different role."""
        parsed = urlparse(self.url)
        netloc = f"{user}:{password}@{parsed.hostname}:{parsed.port}"
        return urlunparse(parsed._replace(netloc=netloc))


@pytest_asyncio.fixture
async def cloned_database(
    postgres_container: PostgresContainer,
    template_database: str,
) -> AsyncGenerator[ClonedDatabase]:
    """Per-test database cloned from the migrated template; dropped at teardown."""
    test_db = f"t_{uuid4().hex[:12]}"
    admin_url = normalize_async_url(postgres_container.get_connection_url(), database="postgres")

    admin = await asyncpg.connect(admin_url)
    try:
        await admin.execute(f'CREATE DATABASE "{test_db}" TEMPLATE "{template_database}"')
    finally:
        await admin.close()

    test_url = normalize_async_url(postgres_container.get_connection_url(), database=test_db)
    pool = await create_pool(test_url, min_size=1, max_size=4)
    try:
        yield ClonedDatabase(pool=pool, url=test_url)
    finally:
        await pool.close()
        admin = await asyncpg.connect(admin_url)
        try:
            await admin.execute(f'DROP DATABASE "{test_db}"')
        finally:
            await admin.close()


@pytest_asyncio.fixture
async def db_pool(cloned_database: ClonedDatabase) -> asyncpg.Pool:
    """The owner-role pool. The common case; most tests want only this."""
    return cloned_database.pool
