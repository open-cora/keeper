"""The idempotency store, against a real Postgres.

Until this file, the Postgres adapter had no test of its own. Whatever
the Access slices happened to drive through it was the whole of its
coverage, so its claim path, its stale-lock takeover and its prune were
reached only incidentally or not at all.

The behaviours are the shared port contract, run here against the
adapter that has to keep them in SQL. The claim path is one
INSERT ... ON CONFLICT DO UPDATE with a WHERE predicate doing the work
that the twin does with a dict lookup and two ifs, which is precisely
why agreeing with the twin is worth asserting rather than assuming.
"""

import asyncpg
import pytest

from keeper.infrastructure.adapters.postgres_idempotency_store import PostgresIdempotencyStore
from tests._port_contracts.idempotency_store import CHECKS, Check

pytestmark = [pytest.mark.integration]


@pytest.fixture
def store(db_pool: asyncpg.Pool) -> PostgresIdempotencyStore:
    return PostgresIdempotencyStore(db_pool)


@pytest.mark.parametrize("check", CHECKS, ids=lambda c: c.__name__)
async def test_the_postgres_idempotency_store_keeps_the_port_contract(
    check: Check, store: PostgresIdempotencyStore
) -> None:
    await check(store)
