"""Cross-cutting idempotency decorator for command handlers.

`with_idempotency(handler, store, *, command_name, serialize_result,
deserialize_result, lock_stale_seconds)` returns a wrapped handler
with full Idempotency-Key support: two-phase claim, 4xx error
caching, stale-lock recovery. The wrap is applied in a bounded
context's wiring module, so every create-style command handler gets
idempotency through one composition point and slices stay focused on
domain logic.

Lives at `aroc/infrastructure/` (not in any single BC) because it
applies uniformly to every BC's command handlers and depends only on
the IdempotencyStore port + the cross-BC handler-call convention
(`(command, *, principal_id, correlation_id, causation_id) -> TResult`).


For each call with a key, the decorator:

  1. Computes the canonical hash of the command body.
  2. Calls `store.claim()`: a single SQL round-trip (in the happy
     path) that either wins the in-flight lock or returns the
     existing outcome.
  3. Dispatches on the outcome:
     - `Claimed` -> run handler. On success, `finalize_success()`
       and return. On a cacheable 4xx exception, `finalize_error()`
       and re-raise the original. On a 5xx / uncacheable exception,
       re-raise without finalizing, the row stays locked and is
       recovered on the next retry via stale-lock takeover.
     - `CachedSuccess` -> return the deserialized cached result.
     - `CachedError` -> raise `CachedHandlerError`; the route layer
       reconstructs the original 4xx response.
     - `LockedRecent` -> raise `IdempotencyClaimLostError` -> 409
       with `Retry-After: 1`. Standard HTTP retry-after semantics.
     - `HashConflict` -> raise `IdempotencyConflictError` -> 422.

## Hashing

Commands MUST be frozen dataclasses (with primitive or nested-
dataclass fields). `hash_command(cmd)` serializes via `asdict` +
`json.dumps(sort_keys=True, default=str)` + SHA256.

`set` and `frozenset` fields on the command get normalized to sorted
lists before hashing, Python's set iteration order varies across
processes (PYTHONHASHSEED randomizes string hashing) so the same
logical set would produce different `repr` and different hashes
under multiple workers, manifesting as spurious 422 "Idempotency-Key
conflict" responses on legitimate retries. Routes that convert JSON
arrays to `frozenset` for command construction (a permission set on a
policy-shaped command, say) rely on this normalization.

## Error classification (4xx caching scope)

`classify_error_status(exc)` maps an exception to its HTTP status
by class-name convention. Returns None for unknown shapes (treated
as 5xx -> not cached -> retry-friendly). The convention codifies
existing routes.py groupings:

  - `Invalid*`           -> 400
  - `UnauthorizedError`  -> 403
  - `*NotFoundError`     -> 404
  - `*AlreadyExistsError`, `*Cannot*Error`, `ConcurrencyError`  -> 409
  - `IdempotencyConflictError`  -> 422

Per-class override via `idempotency_http_status: ClassVar[int]`
attribute (rare; convention covers the existing 67-class spectrum).

## Key length

Capped at `_MAX_KEY_LENGTH` (255 chars, matching Stripe's limit).
Longer keys raise `ValueError` from the decorator before any store
lookup or handler invocation.
"""

import hashlib
import json
from collections.abc import Callable
from dataclasses import asdict, is_dataclass
from typing import Any, Protocol, cast
from uuid import UUID

from keeper.infrastructure.logging import get_logger
from keeper.infrastructure.ports import (
    CachedError,
    CachedHandlerError,
    CachedSuccess,
    Claimed,
    HashConflict,
    IdempotencyClaimLostError,
    IdempotencyConflictError,
    IdempotencyStore,
    LockedRecent,
)
from keeper.shared.reserved_ids import NIL_SENTINEL_ID

_MAX_KEY_LENGTH = 255

_log = get_logger(__name__)


def _noop_serialize(_value: None) -> None:
    """Serialize codec for None-returning handlers idempotency-wrapped.

    `with_idempotency` requires a serialize_result / deserialize_result
    pair; for handlers that return None there is no payload to round-
    trip. The pair stays symmetric (serializes None to None, deserializes
    None to None) so the cache hit replays "success with None".

    Candidates: any command slice whose handler returns nothing and
    whose route answers 204.
    """
    return None


def _noop_deserialize(_value: object) -> None:
    """Inverse of `NOOP_SERIALIZE`."""
    return None


NOOP_SERIALIZE = _noop_serialize
NOOP_DESERIALIZE = _noop_deserialize


def _normalize_for_hash(obj: Any) -> Any:
    """Recursively normalize containers so the JSON form is hash-stable.

    `set` and `frozenset` are sorted by string form, without this,
    PYTHONHASHSEED randomizes set iteration across workers and
    breaks idempotency. `dict` and `list`/`tuple` recurse into their
    elements.
    """
    if isinstance(obj, (set, frozenset)):
        items_set = cast("set[Any] | frozenset[Any]", obj)
        return sorted((_normalize_for_hash(item) for item in items_set), key=str)
    if isinstance(obj, dict):
        items_dict = cast("dict[Any, Any]", obj)
        return {k: _normalize_for_hash(v) for k, v in items_dict.items()}
    if isinstance(obj, (list, tuple)):
        items_seq = cast("list[Any] | tuple[Any, ...]", obj)
        return [_normalize_for_hash(item) for item in items_seq]
    return obj


def hash_command(command: Any) -> str:
    """SHA256 hex digest of canonical JSON of the command's dict form."""
    if not is_dataclass(command) or isinstance(command, type):
        msg = (
            f"hash_command requires a dataclass instance, got {type(command).__name__}. "
            "Commands across the codebase are frozen dataclasses by convention."
        )
        raise TypeError(msg)
    normalized = _normalize_for_hash(asdict(command))
    canonical = json.dumps(normalized, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


def classify_error_status(exc: BaseException) -> int | None:
    """Map a domain exception class to its HTTP status by class-name convention.

    Returns None when the exception isn't a known cacheable shape
    (treated as 5xx -> not cached, retry-friendly). Per-class override
    via `idempotency_http_status: ClassVar[int]` attribute on the
    exception class.
    """
    explicit = getattr(type(exc), "idempotency_http_status", None)
    if explicit is not None:
        return int(explicit)
    name = type(exc).__name__
    if name.startswith("Invalid"):
        return 400
    if name == "UnauthorizedError":
        return 403
    if name.endswith("NotFoundError"):
        return 404
    if name.endswith("AlreadyExistsError"):
        return 409
    if "Cannot" in name and name.endswith("Error"):
        return 409
    if name == "ConcurrencyError":
        return 409
    if name == "IdempotencyConflictError":
        return 422
    return None


def _full_class_name(exc: BaseException) -> str:
    """`module.qualname` of the exception's class, for cached error_type."""
    cls = type(exc)
    return f"{cls.__module__}.{cls.__qualname__}"


class _BareHandler[TCommand, TResult](Protocol):
    async def __call__(
        self,
        command: TCommand,
        *,
        principal_id: UUID,
        correlation_id: UUID,
        causation_id: UUID | None = None,
        surface_id: UUID = NIL_SENTINEL_ID,
    ) -> TResult: ...


class _IdempotentHandler[TCommand, TResult](Protocol):
    async def __call__(
        self,
        command: TCommand,
        *,
        principal_id: UUID,
        correlation_id: UUID,
        causation_id: UUID | None = None,
        surface_id: UUID = NIL_SENTINEL_ID,
        idempotency_key: str | None = None,
    ) -> TResult: ...


def with_idempotency[TCommand, TResult](
    handler: _BareHandler[TCommand, TResult],
    store: IdempotencyStore,
    *,
    command_name: str,
    serialize_result: Callable[[TResult], Any],
    deserialize_result: Callable[[Any], TResult],
    lock_stale_seconds: int,
) -> _IdempotentHandler[TCommand, TResult]:
    """Wrap a bare command handler with two-phase Idempotency-Key support.

    `lock_stale_seconds` is sourced from `Settings.idempotency_lock_stale_seconds`
    at wire-time. It controls how long a locked row sits before being
    re-claimable by another request (worker-crash recovery).
    """

    async def wrapped(
        command: TCommand,
        *,
        principal_id: UUID,
        correlation_id: UUID,
        causation_id: UUID | None = None,
        surface_id: UUID = NIL_SENTINEL_ID,
        idempotency_key: str | None = None,
    ) -> TResult:
        if idempotency_key is None:
            return await handler(
                command,
                principal_id=principal_id,
                correlation_id=correlation_id,
                causation_id=causation_id,
                surface_id=surface_id,
            )

        if len(idempotency_key) > _MAX_KEY_LENGTH:
            msg = f"Idempotency-Key length {len(idempotency_key)} exceeds maximum {_MAX_KEY_LENGTH}"
            raise ValueError(msg)

        cmd_hash = hash_command(command)
        outcome = await store.claim(
            principal_id,
            idempotency_key,
            surface_id,
            cmd_hash,
            command_name,
            lock_stale_seconds=lock_stale_seconds,
        )

        log_ctx = {
            "command_name": command_name,
            "principal_id": str(principal_id),
            "correlation_id": str(correlation_id),
            "key": idempotency_key,
        }

        match outcome:
            case Claimed():
                _log.info("idempotency.claimed", **log_ctx)
                try:
                    result = await handler(
                        command,
                        principal_id=principal_id,
                        correlation_id=correlation_id,
                        causation_id=causation_id,
                        surface_id=surface_id,
                    )
                except Exception as exc:
                    status = classify_error_status(exc)
                    if status is not None and 400 <= status < 500:
                        await store.finalize_error(
                            principal_id,
                            idempotency_key,
                            surface_id,
                            error_type=_full_class_name(exc),
                            error_msg=str(exc),
                        )
                        _log.info(
                            "idempotency.cached_error",
                            error_type=_full_class_name(exc),
                            http_status=status,
                            **log_ctx,
                        )
                    else:
                        # 5xx or unknown shape: leave the row locked.
                        # Stale-lock recovery will let the next retry
                        # re-claim after `lock_stale_seconds`.
                        _log.info(
                            "idempotency.uncached_error",
                            error_type=_full_class_name(exc),
                            **log_ctx,
                        )
                    raise
                await store.finalize_success(
                    principal_id,
                    idempotency_key,
                    surface_id,
                    serialize_result(result),
                )
                _log.info("idempotency.cached_success", **log_ctx)
                return result
            case CachedSuccess(result=cached):
                _log.info("idempotency.hit_success", **log_ctx)
                return deserialize_result(cached)
            case CachedError(error_type=error_type, error_msg=error_msg):
                _log.info(
                    "idempotency.hit_error",
                    cached_error_type=error_type,
                    **log_ctx,
                )
                raise CachedHandlerError(error_type=error_type, error_msg=error_msg)
            case LockedRecent(locked_at=locked_at):
                _log.info(
                    "idempotency.claim_lost",
                    locked_at=locked_at.isoformat(),
                    **log_ctx,
                )
                raise IdempotencyClaimLostError(key=idempotency_key, locked_at=locked_at)
            case HashConflict(expected_hash=expected, actual_hash=actual):
                _log.info(
                    "idempotency.conflict",
                    expected_hash=expected,
                    actual_hash=actual,
                    **log_ctx,
                )
                raise IdempotencyConflictError(
                    key=idempotency_key,
                    expected_hash=expected,
                    actual_hash=actual,
                )

    return wrapped


__all__ = [
    "NOOP_DESERIALIZE",
    "NOOP_SERIALIZE",
    "classify_error_status",
    "hash_command",
    "with_idempotency",
]
