"""In-memory `IdempotencyStore` for unit tests and the `test` app environment.

Mirrors the Postgres adapter's contract: same
`(principal_id, key, surface_id)` namespacing, same
`claim` / `finalize_*` / `prune` semantics, same stale-lock
recovery rules. A `threading.Lock` guards the dict so concurrent
tasks see consistent state. Not durable across process restarts
(use the Postgres adapter for production / integration).
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from threading import Lock
from typing import Any
from uuid import UUID

from keeper.infrastructure.ports.idempotency_store import (
    CachedError,
    CachedSuccess,
    Claimed,
    ClaimOutcome,
    HashConflict,
    LockedRecent,
)


@dataclass
class _Row:
    """Tri-state row, matching the PG CHECK constraint:
    in-flight (locked_at, no result/error),
    completed-success (result, no locked_at/error),
    completed-error (error, no locked_at/result)."""

    command_hash: str
    command_name: str
    created_at: datetime
    locked_at: datetime | None = None
    result: Any = None
    error_type: str | None = None
    error_msg: str | None = None


class InMemoryIdempotencyStore:
    """Thread-safe in-memory implementation of the IdempotencyStore port."""

    def __init__(self) -> None:
        self._records: dict[tuple[UUID, str, UUID], _Row] = {}
        self._lock = Lock()

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
        now = datetime.now(tz=UTC)
        stale_cutoff = now - timedelta(seconds=lock_stale_seconds)
        with self._lock:
            existing = self._records.get((principal_id, key, surface_id))
            if existing is None:
                self._records[(principal_id, key, surface_id)] = _Row(
                    command_hash=command_hash,
                    command_name=command_name,
                    created_at=now,
                    locked_at=now,
                )
                return Claimed()
            # Stale-lock takeover.
            if existing.locked_at is not None and existing.locked_at < stale_cutoff:
                existing.command_hash = command_hash
                existing.command_name = command_name
                existing.locked_at = now
                # Stale takeover wipes any prior partial state (defensive
                # against CHECK violations that shouldn't happen).
                existing.result = None
                existing.error_type = None
                existing.error_msg = None
                return Claimed()
            # Recent in-flight lock.
            if existing.locked_at is not None:
                return LockedRecent(locked_at=existing.locked_at)
            # Completed: classify by hash + result/error.
            if existing.command_hash != command_hash:
                return HashConflict(
                    expected_hash=existing.command_hash,
                    actual_hash=command_hash,
                )
            if existing.result is not None:
                return CachedSuccess(
                    command_hash=existing.command_hash,
                    command_name=existing.command_name,
                    result=existing.result,
                )
            if existing.error_type is not None:
                # Both error_type and error_msg present per CHECK constraint.
                assert existing.error_msg is not None
                return CachedError(
                    command_hash=existing.command_hash,
                    command_name=existing.command_name,
                    error_type=existing.error_type,
                    error_msg=existing.error_msg,
                )
            # Unreachable per the tri-state invariant; treat as Claimed
            # defensively (matches PG adapter behavior).
            return Claimed()

    async def finalize_success(
        self,
        principal_id: UUID,
        key: str,
        surface_id: UUID,
        result: Any,
    ) -> None:
        with self._lock:
            row = self._records.get((principal_id, key, surface_id))
            if row is None:
                return
            row.locked_at = None
            row.result = result
            row.error_type = None
            row.error_msg = None

    async def finalize_error(
        self,
        principal_id: UUID,
        key: str,
        surface_id: UUID,
        error_type: str,
        error_msg: str,
    ) -> None:
        with self._lock:
            row = self._records.get((principal_id, key, surface_id))
            if row is None:
                return
            row.locked_at = None
            row.result = None
            row.error_type = error_type
            row.error_msg = error_msg

    async def prune(self, *, ttl_hours: int) -> int:
        cutoff = datetime.now(tz=UTC) - timedelta(hours=ttl_hours)
        with self._lock:
            to_delete = [
                k
                for k, row in self._records.items()
                if row.created_at < cutoff and row.locked_at is None
            ]
            for k in to_delete:
                del self._records[k]
        return len(to_delete)
