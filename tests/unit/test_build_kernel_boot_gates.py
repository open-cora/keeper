"""The production boot gates refuse rather than fall back.

Both defaults in `build_kernel` are permissive, and both are correct for
tests: `AllowAllAuthorize` lets a unit test exercise a handler without
standing up a policy, and an absent `require_authenticated_principal` lets a
developer curl the API.

Permissive defaults are also exactly how an authorization gate ends up off in
production with nothing recording that it was skipped. The reconciliation is
these refusals, so this file exercises the WRONG configuration and asserts the
process will not start.

Three ways to reach a permissive adapter on a production tier, and three
refusals, because each has a different remedy: pass a factory, configure a
policy, or stop returning `AllowAllAuthorize` from the factory you passed.
The third is asserted in `tests/integration/test_boot_gates_postgres.py`,
because checking what a factory BUILT means building it, and building this
one means an event store.
"""

import pytest

from keeper.infrastructure.deps import build_kernel
from keeper.infrastructure.ports import AllowAllAuthorize, Authorize, EventStore
from keeper.infrastructure.settings import Settings

pytestmark = pytest.mark.unit


def _stub_authorize_factory(settings: Settings, event_store: EventStore) -> Authorize:
    """A factory of the right shape, so the SECOND gate is what refuses.

    Absent-factory is the first test's subject. Reaching the principal gate
    means getting past that check, so this has to satisfy `AuthorizeFactory`
    rather than stand in for it loosely.

    Spelled out rather than swallowing `*args`, which is what it used to do.
    `AuthorizeFactory` is a Protocol instead of a `Callable` alias so that a
    factory of the wrong shape fails the type checker here rather than at
    boot, and a catch-all is the one signature that matches whatever the
    protocol says. The strictness was being paid for and not collected.
    """
    _ = (settings, event_store)
    return AllowAllAuthorize()


@pytest.mark.parametrize("env", ["prod", "production", "staging"])
async def test_production_tier_refuses_to_boot_without_an_authorize_factory(env: str) -> None:
    settings = Settings(app_env=env, require_authenticated_principal=True)
    with pytest.raises(ValueError, match="requires authorize_factory"):
        await build_kernel(settings=settings)


@pytest.mark.parametrize("env", ["prod", "production", "staging"])
async def test_production_tier_refuses_to_boot_without_authenticated_principals(env: str) -> None:
    """Without the header check, any caller can claim any principal."""
    settings = Settings(app_env=env, require_authenticated_principal=False)
    with pytest.raises(ValueError, match="REQUIRE_AUTHENTICATED_PRINCIPAL"):
        await build_kernel(
            settings=settings,
            authorize_factory=_stub_authorize_factory,
        )


@pytest.mark.parametrize("env", ["prod", "production", "staging"])
async def test_production_tier_refuses_to_boot_with_no_policy_configured(env: str) -> None:
    """The real factory hands back AllowAll when AUTHZ_POLICY_ID is unset.

    Answerable from settings alone, so it is refused before the pool is
    opened. The companion check, on the adapter a factory actually
    returns, cannot be: building one needs an event store. It lives in
    the integration tier, where a database exists.
    """
    settings = Settings(app_env=env, require_authenticated_principal=True)
    with pytest.raises(ValueError, match="AUTHZ_POLICY_ID"):
        await build_kernel(settings=settings, authorize_factory=_stub_authorize_factory)


async def test_test_env_builds_an_in_memory_kernel_with_no_pool() -> None:
    """The permissive path, asserted so the refusals above are not vacuous.

    If test mode also refused, the two tests above would pass for the wrong
    reason and this file would prove nothing about production specifically.
    """
    kernel, teardown = await build_kernel(settings=Settings(app_env="test"))
    try:
        assert kernel.pool is None
        assert kernel.authz is not None
        assert kernel.schema_posture == "matched"
    finally:
        await teardown()
