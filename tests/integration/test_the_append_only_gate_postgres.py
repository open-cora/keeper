"""The boot gate that refuses a role which can rewrite the record.

`tests/integration/test_events_append_only_postgres.py` proves the grants
on `keeper_app` are right. It says nothing about whether the running
server uses that role, and for months the deployment did not: three
documents described an append-only guarantee that the connection string
had quietly opted out of.

This is the check that closes the gap, so these are its two directions
and the tier rule between them.

Both roles are reached against one database, because what is being
checked is a property of the connection rather than of the schema. The
owner is the role every other test connects as, which is also why the
mistake was invisible: nothing in the suite had ever asked the question.
"""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false

import asyncpg
import pytest

from keeper.infrastructure.schema import RewritableHistoryError, verify_append_only_role
from tests.integration.conftest import ClonedDatabase

pytestmark = [pytest.mark.integration]

APP_ROLE = "keeper_app"


async def _app_role_pool(database: ClonedDatabase) -> asyncpg.Pool:
    pool = await asyncpg.create_pool(database.url_as(APP_ROLE, APP_ROLE), min_size=1, max_size=1)
    assert pool is not None
    return pool


async def test_the_application_role_is_reported_as_sealed(
    cloned_database: ClonedDatabase,
) -> None:
    pool = await _app_role_pool(cloned_database)
    try:
        assert await verify_append_only_role(pool, refuse=True) is True
    finally:
        await pool.close()


async def test_the_owner_is_reported_as_rewritable(
    cloned_database: ClonedDatabase,
) -> None:
    """Below the production tier this is a warning, so it returns rather than
    raising, and the value is what a caller would act on."""
    assert await verify_append_only_role(cloned_database.pool, refuse=False) is False


async def test_the_owner_is_refused_above_the_production_tier(
    cloned_database: ClonedDatabase,
) -> None:
    with pytest.raises(RewritableHistoryError) as refused:
        await verify_append_only_role(cloned_database.pool, refuse=True)

    assert refused.value.role
    assert "keeper_app" in str(refused.value), (
        "the refusal has to name the role to point at, or an operator reading "
        "it at three in the morning learns only that something is wrong"
    )


async def test_the_application_role_can_read_the_schema_version(
    cloned_database: ClonedDatabase,
) -> None:
    """The grant that makes the restricted role usable at all.

    Without it the process dies in the schema check before it reaches
    anything else, which is the reason the deployment ran as the owner.
    """
    pool = await _app_role_pool(cloned_database)
    try:
        async with pool.acquire() as conn:
            applied = await conn.fetchval(
                "SELECT coalesce(max(version), '') "
                "FROM atlas_schema_revisions.atlas_schema_revisions"
            )
    finally:
        await pool.close()

    assert applied


async def test_the_application_role_cannot_edit_the_schema_version(
    cloned_database: ClonedDatabase,
) -> None:
    """Read is the whole grant. A role that could write its own schema version
    could tell the gate above any schema was applied."""
    pool = await _app_role_pool(cloned_database)
    try:
        async with pool.acquire() as conn:
            with pytest.raises(asyncpg.InsufficientPrivilegeError):
                await conn.execute("DELETE FROM atlas_schema_revisions.atlas_schema_revisions")
    finally:
        await pool.close()
