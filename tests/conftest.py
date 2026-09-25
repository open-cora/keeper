"""Pytest configuration and shared fixtures.

`APP_ENV=test` is set before any test imports, so unit and contract tests that
build an app via `create_app()` get the in-memory adapters by default.
Integration tests build their own kernel against `db_pool`; e2e tests override
the environment so the lifespan takes the Postgres branch.

## Session-scoped Postgres container, one per xdist worker

`postgres_container` and `template_database` live here rather than in the
integration tier's conftest so the integration and e2e fixtures share one
container per session.

The template-database strategy: migrations apply ONCE into the container's
default database, and each per-test database is created with `CREATE DATABASE
... TEMPLATE`, which Postgres satisfies by file copy in tens of milliseconds.
That buys full isolation per test without any TRUNCATE bookkeeping, and
without the cross-test coupling a shared database creates.

Under pytest-xdist each worker is a separate process running its own session,
so `scope="session"` naturally yields one container per worker. Sharing one
container ACROSS workers is a known testcontainers-python footgun
(testcontainers-python#567: ports get reassigned to the wrong instance during
overlapping start and stop), and per-worker containers sidestep it entirely
for about two seconds of startup each.
"""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false

import os
from collections.abc import Generator
from pathlib import Path
from urllib.parse import urlparse

import asyncpg
import pytest
import pytest_asyncio
from hypothesis import HealthCheck, Verbosity, settings
from testcontainers.postgres import PostgresContainer

from keeper.infrastructure.schema import parse_versions
from tests._postgres import normalize_async_url

os.environ.setdefault("APP_ENV", "test")

# Hypothesis profiles.
# `dev` (the local default) keeps the example database on and allows shrinking:
#   the fast feedback loop a developer wants.
# `ci` derandomizes the seed so xdist workers do not collide on the example
#   database, disables the example database entirely to avoid worker write
#   contention, drops the deadline so a slow runner does not flake, and
#   silences the function-scoped-fixture health check that trips on
#   pytest-asyncio's per-test event loop.
settings.register_profile("dev", deadline=None)
settings.register_profile(
    "ci",
    deadline=None,
    derandomize=True,
    database=None,
    print_blob=True,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
    verbosity=Verbosity.normal,
)
settings.load_profile("ci" if os.environ.get("CI") == "true" else "dev")

_MIGRATIONS_DIR = Path(__file__).resolve().parents[3] / "infra" / "atlas" / "migrations"


def _migration_files() -> list[Path]:
    return sorted(_MIGRATIONS_DIR.glob("*.sql"))


def _read_migration_statements() -> list[str]:
    """Read migration .sql files in order. Each file executes as one batch."""
    return [f.read_text() for f in _migration_files()]


# Atlas's bookkeeping, which this fixture has to stand in for.
#
# The suite applies migrations by executing the .sql files directly and never
# runs Atlas, so nothing here creates the revisions table Atlas writes when IT
# applies them. That gap is invisible until something reads the table:
# `build_kernel` checks the applied schema version at boot, and without this
# the whole suite would take the never-migrated branch, so the check would
# ship having never run in its real mode.
#
# Only the column the application reads is declared. A fuller replica would
# mean guessing at columns nothing here uses, and a wrong guess is worse than
# an honest subset: these databases are built by this fixture and never handed
# to Atlas.
_ATLAS_REVISIONS_DDL = """
CREATE SCHEMA IF NOT EXISTS atlas_schema_revisions;
CREATE TABLE IF NOT EXISTS atlas_schema_revisions.atlas_schema_revisions (
    version text PRIMARY KEY
);
"""


@pytest.fixture(scope="session")
def postgres_container(worker_id: str) -> Generator[PostgresContainer]:
    """One Postgres container per xdist worker, or one per session without xdist.

    `worker_id` is `"master"` outside xdist; pytest-xdist provides the fixture
    and resolves it to `gw0`, `gw1`, and so on per worker process. It is woven
    into the container name purely so `docker ps` stays legible while debugging
    and so an interrupted run cannot collide on the name.
    """
    container = PostgresContainer("pgvector/pgvector:pg18", driver=None)
    container.with_name(f"aroc-pgtest-{worker_id}")
    container.start()
    try:
        yield container
    finally:
        container.stop()


@pytest_asyncio.fixture(scope="session")
async def template_database(postgres_container: PostgresContainer) -> str:
    """Apply migrations once per worker; the resulting database is the clone template."""
    base_url = normalize_async_url(postgres_container.get_connection_url())
    template_name = urlparse(base_url).path.lstrip("/")

    conn = await asyncpg.connect(base_url)
    try:
        for sql in _read_migration_statements():
            await conn.execute(sql)
        await conn.execute(_ATLAS_REVISIONS_DDL)
        await conn.executemany(
            "INSERT INTO atlas_schema_revisions.atlas_schema_revisions (version) VALUES ($1)",
            [(version,) for version in parse_versions(_migration_files())],
        )
    finally:
        await conn.close()

    return template_name
