"""The idempotency wrapper, against a synthetic command.

The wrapper is chassis: it takes any frozen dataclass command and knows
nothing about the slice it wraps. These tests use a command of their own
rather than a real one, because the behaviour worth pinning is what
happens when two calls under the same key disagree, and whether any
shipping command happens to carry a field is not the wrapper's business.

That independence is the point. This coverage previously rode on the
Access surface, where the two bodies differed because `RegisterActor`
had a field. A command with no fields cannot hash two ways, so the
conflict path stopped being reachable from there the moment the field
went, silently, with every test still green.
"""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID, uuid4

import pytest

from keeper.infrastructure.adapters.in_memory_idempotency_store import (
    InMemoryIdempotencyStore,
)
from keeper.infrastructure.ports import IdempotencyConflictError
from keeper.infrastructure.slices.idempotency import hash_command, with_idempotency
from keeper.shared.reserved_ids import NIL_SENTINEL_ID

pytestmark = pytest.mark.unit


@dataclass(frozen=True)
class _Ask:
    """A command shaped like any other: frozen, with a primitive field."""

    subject: str


@dataclass(frozen=True)
class _AskNothing:
    """A command with no fields, the shape `RegisterActor` now has."""


class _Handler(Protocol):
    """The bare-handler shape the wrapper accepts, pinned to `_Ask`."""

    async def __call__(
        self,
        command: _Ask,
        *,
        principal_id: UUID,
        correlation_id: UUID,
        causation_id: UUID | None = None,
        surface_id: UUID = NIL_SENTINEL_ID,
    ) -> UUID: ...


def _counting_handler() -> tuple[_Handler, list[_Ask]]:
    seen: list[_Ask] = []

    async def handler(
        command: _Ask,
        *,
        principal_id: UUID,
        correlation_id: UUID,
        causation_id: UUID | None = None,
        surface_id: UUID = NIL_SENTINEL_ID,
    ) -> UUID:
        _ = (principal_id, correlation_id, causation_id, surface_id)
        seen.append(command)
        return uuid4()

    return handler, seen


def _wrap(handler: _Handler):
    return with_idempotency(
        handler,
        InMemoryIdempotencyStore(),
        command_name="Ask",
        serialize_result=str,
        deserialize_result=lambda raw: UUID(str(raw)),
        lock_stale_seconds=60,
    )


async def test_two_calls_without_a_key_both_reach_the_handler() -> None:
    """The baseline the replay test below is measured against."""
    handler, seen = _counting_handler()
    wrapped = _wrap(handler)
    caller = uuid4()

    first = await wrapped(_Ask("a"), principal_id=caller, correlation_id=uuid4())
    second = await wrapped(_Ask("a"), principal_id=caller, correlation_id=uuid4())

    assert len(seen) == 2
    assert first != second


async def test_replaying_a_key_returns_the_first_result_without_rerunning() -> None:
    handler, seen = _counting_handler()
    wrapped = _wrap(handler)
    caller = uuid4()

    first = await wrapped(
        _Ask("a"), principal_id=caller, correlation_id=uuid4(), idempotency_key="k"
    )
    second = await wrapped(
        _Ask("a"), principal_id=caller, correlation_id=uuid4(), idempotency_key="k"
    )

    assert second == first
    assert len(seen) == 1, "the cached answer must not re-run the handler"


async def test_reusing_a_key_with_a_different_command_is_refused() -> None:
    """A cached answer cannot be the right answer to a different question."""
    handler, seen = _counting_handler()
    wrapped = _wrap(handler)
    caller = uuid4()

    await wrapped(_Ask("a"), principal_id=caller, correlation_id=uuid4(), idempotency_key="k")
    with pytest.raises(IdempotencyConflictError):
        await wrapped(_Ask("b"), principal_id=caller, correlation_id=uuid4(), idempotency_key="k")

    assert len(seen) == 1, "the conflicting call must not have run"


async def test_the_same_key_under_a_different_principal_is_a_separate_namespace() -> None:
    """The cache key is (principal, key, surface), not the key alone."""
    handler, seen = _counting_handler()
    wrapped = _wrap(handler)

    await wrapped(_Ask("a"), principal_id=uuid4(), correlation_id=uuid4(), idempotency_key="k")
    await wrapped(_Ask("a"), principal_id=uuid4(), correlation_id=uuid4(), idempotency_key="k")

    assert len(seen) == 2


def test_a_command_with_no_fields_hashes_the_same_every_time() -> None:
    """Why the conflict test above cannot be written against `RegisterActor`.

    Two calls carrying a fieldless command are indistinguishable to the
    hash, so they can never conflict. Stated here so that the coverage
    living at this tier reads as deliberate rather than misplaced.
    """
    assert hash_command(_AskNothing()) == hash_command(_AskNothing())
    assert hash_command(_Ask("a")) != hash_command(_Ask("b"))
