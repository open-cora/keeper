"""The boot gate that can only be checked after the adapter is built.

Its two siblings in `tests/unit/test_build_kernel_boot_gates.py` read
settings and refuse before anything is opened. This one cannot: the
question is what the factory RETURNED, and returning it means
constructing it, which means an event store, which means a pool.

That split is the point rather than an inconvenience. A gate that only
reads configuration is satisfied by a factory that ignores configuration,
and the factory is supplied by the caller.
"""

# asyncpg ships no type information for Connection.fetchval, so the two
# backend counts below resolve to Unknown. Suppressed at module level
# because the surface is those two calls and they return a bare integer.
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false

from uuid import uuid4

import pytest

from keeper.authority import PolicyAuthorize, build_authorize
from keeper.infrastructure.deps import build_kernel
from keeper.infrastructure.ports import AllowAllAuthorize, Authorize, EventStore
from keeper.infrastructure.settings import Settings
from tests.integration.conftest import ClonedDatabase

pytestmark = [pytest.mark.integration]


def _permissive_factory(settings: Settings, event_store: EventStore) -> Authorize:
    """A factory that satisfies the settings gates and opens the door anyway.

    Not a strawman: this is what the unit tier's own stub does, and what
    a factory left half-written during a refactor would do.

    Its signature is spelled out for the reason the unit tier's stub gives:
    a catch-all matches any protocol and so checks none.
    """
    _ = (settings, event_store)
    return AllowAllAuthorize()


def _production_settings(cloned_database: ClonedDatabase) -> Settings:
    return Settings(
        app_env="prod",
        database_url=cloned_database.url,
        require_authenticated_principal=True,
        authz_policy_id=uuid4(),
    )


async def test_a_production_tier_refuses_a_factory_that_returns_the_permissive_adapter(
    cloned_database: ClonedDatabase,
) -> None:
    """Every settings gate satisfied, and the door still open."""
    with pytest.raises(ValueError, match="AllowAllAuthorize"):
        await build_kernel(
            settings=_production_settings(cloned_database),
            authorize_factory=_permissive_factory,
        )


async def test_the_refusal_closes_the_pool_it_had_already_opened(
    cloned_database: ClonedDatabase,
) -> None:
    """The check runs after the database is reached, so it has to clean up.

    Raising past an open pool leaves a connection held by a process on
    its way out. Asserted by counting the backends this deployment's own
    settings would have opened, since the fixture holds a pool of its own
    against the same database.
    """
    settings = _production_settings(cloned_database)
    before = await cloned_database.pool.fetchval(
        "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database()"
    )

    with pytest.raises(ValueError, match="AllowAllAuthorize"):
        await build_kernel(settings=settings, authorize_factory=_permissive_factory)

    after = await cloned_database.pool.fetchval(
        "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database()"
    )
    assert after <= before, f"{after - before} connections survived the refusal"


async def test_a_production_tier_boots_when_the_factory_returns_a_real_adapter(
    cloned_database: ClonedDatabase,
) -> None:
    """The permissive path, so the refusals above are not vacuous.

    If a production tier refused whatever it was handed, every test here
    would pass for the wrong reason and none would say anything about
    the adapter.
    """
    kernel, teardown = await build_kernel(
        settings=_production_settings(cloned_database),
        authorize_factory=build_authorize,
    )
    try:
        assert isinstance(kernel.authz, PolicyAuthorize)
    finally:
        await teardown()
