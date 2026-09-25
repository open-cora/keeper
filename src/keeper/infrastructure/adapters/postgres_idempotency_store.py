"""Postgres-backed `IdempotencyStore` adapter.

Implements the new port surface (`claim`, `finalize_success`,
`finalize_error`, `prune`) on top of the `idempotency_keys` table.

## Atomic claim via single SQL statement (Brandur Leach pattern)

`claim()` is a single round-trip in the happy path. The
INSERT ... ON CONFLICT DO UPDATE statement combines three logical
paths:

  - **Fresh INSERT** (row didn't exist): `RETURNING` returns the new
    row -> `Claimed`.
  - **Stale-lock takeover** (row exists, locked_at IS NOT NULL,
    locked longer than `lock_stale_seconds`): the WHERE predicate on
    DO UPDATE matches, the UPDATE fires, `RETURNING` returns the
    updated row -> `Claimed`. Worker-crash recovery: free.
  - **Lost or already-completed** (row exists with locked_at IS NULL,
    or with a recent locked_at): WHERE predicate doesn't match, no
    UPDATE, `RETURNING` returns nothing. A second SELECT classifies
    the outcome (CachedSuccess / CachedError / LockedRecent /
    HashConflict).

The two-statement path is only taken when we LOSE the race; the hot
path (uncontended retry) is one SQL round-trip.

## CHECK constraint

Migration 20260512330000 enforces a tri-state CHECK on the row:
in-flight (locked_at, no result/error), completed-success (result,
no locked_at/error), completed-error (error, no locked_at/result).
Any adapter bug that would leave a row in an invalid state raises
loudly at write time, not silently on next read.
"""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false

from typing import Any
from uuid import UUID

import asyncpg

from keeper.infrastructure.ports.idempotency_store import (
    CachedError,
    CachedSuccess,
    Claimed,
    ClaimOutcome,
    HashConflict,
    LockedRecent,
)

_CLAIM_SQL = """
INSERT INTO idempotency_keys
    (principal_id, key, surface_id, command_hash, command_name, locked_at)
VALUES ($1, $2, $3, $4, $5, now())
ON CONFLICT (principal_id, key, surface_id) DO UPDATE
    SET locked_at    = now(),
        command_hash = EXCLUDED.command_hash,
        command_name = EXCLUDED.command_name
    WHERE idempotency_keys.locked_at IS NOT NULL
      AND idempotency_keys.locked_at < now() - make_interval(secs => $6::int)
RETURNING locked_at
"""

_INSPECT_SQL = """
SELECT command_hash, command_name, locked_at, result, error_type, error_msg
FROM idempotency_keys
WHERE principal_id = $1 AND key = $2 AND surface_id = $3
"""

_FINALIZE_SUCCESS_SQL = """
UPDATE idempotency_keys
SET locked_at = NULL, result = $4, error_type = NULL, error_msg = NULL
WHERE principal_id = $1 AND key = $2 AND surface_id = $3
"""

_FINALIZE_ERROR_SQL = """
UPDATE idempotency_keys
SET locked_at = NULL, result = NULL, error_type = $4, error_msg = $5
WHERE principal_id = $1 AND key = $2 AND surface_id = $3
"""

_PRUNE_SQL = """
DELETE FROM idempotency_keys
WHERE created_at < now() - make_interval(hours => $1::int)
  AND locked_at IS NULL
"""


class PostgresIdempotencyStore:
    """asyncpg-backed `IdempotencyStore` implementation."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def claim(
        self,
        principal_id: UUID,
        key: str,
        surface_id: UUID,
        command_hash: str,
        command_name: str,
        *,
        lock_stale_seconds: int,
    ) -> ClaimOutcome:
        async with self._pool.acquire() as conn:
            inserted = await conn.fetchval(
                _CLAIM_SQL,
                principal_id,
                key,
                surface_id,
                command_hash,
                command_name,
                lock_stale_seconds,
            )
            if inserted is not None:
                # Fresh INSERT or stale-lock takeover: we hold the lock now.
                return Claimed()
            # Lost the race or row already completed; classify.
            row = await conn.fetchrow(_INSPECT_SQL, principal_id, key, surface_id)

        if row is None:
            # TOCTOU between INSERT...ON CONFLICT and INSPECT (extremely
            # rare; only if a concurrent prune deletes the row between
            # the two statements). Treat as fresh Claim and let the
            # event-store optimistic-lock backstop catch any duplicate.
            return Claimed()

        existing_hash = str(row["command_hash"])
        if row["locked_at"] is not None:
            return LockedRecent(locked_at=row["locked_at"])
        if existing_hash != command_hash:
            return HashConflict(
                expected_hash=existing_hash,
                actual_hash=command_hash,
            )
        if row["result"] is not None:
            return CachedSuccess(
                command_hash=existing_hash,
                command_name=str(row["command_name"]),
                result=row["result"],
            )
        if row["error_type"] is not None:
            return CachedError(
                command_hash=existing_hash,
                command_name=str(row["command_name"]),
                error_type=str(row["error_type"]),
                error_msg=str(row["error_msg"]),
            )
        # Unreachable per the CHECK constraint; treat as Claimed
        # defensively (handler retry produces a new outcome; the
        # optimistic-lock backstop protects state).
        return Claimed()

    async def finalize_success(
        self,
        principal_id: UUID,
        key: str,
        surface_id: UUID,
        result: Any,
    ) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(_FINALIZE_SUCCESS_SQL, principal_id, key, surface_id, result)

    async def finalize_error(
        self,
        principal_id: UUID,
        key: str,
        surface_id: UUID,
        error_type: str,
        error_msg: str,
    ) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                _FINALIZE_ERROR_SQL,
                principal_id,
                key,
                surface_id,
                error_type,
                error_msg,
            )

    async def prune(self, *, ttl_hours: int) -> int:
        async with self._pool.acquire() as conn:
            result = await conn.execute(_PRUNE_SQL, ttl_hours)
        # asyncpg returns "DELETE N" as the command tag string; parse N.
        return int(result.split()[-1]) if result else 0
