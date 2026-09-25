"""IdGenerator port: produces aggregate, decision, event, and command IDs.

Default adapter generates UUIDv7 (time-ordered, good for B-tree index locality
and natural sort). UUIDv7 is the standard pick for event-sourced systems where
keys are frequently inserted in roughly time order.

Why we don't use Postgres 18's native `uuidv7()` function: per
the non-determinism convention, every non-deterministic value
the decider depends on (clock, IDs, random, HTTP, LLM, FS) is injected via
port from the handler and CAPTURED in the event payload (capture, don't
recompute). Letting the database generate IDs at INSERT time would mean the
decider returns events without IDs, the IDs are assigned non-deterministically
on persistence, and replays would not be reproducible. Handler-side
generation through this port preserves replay determinism. The PG18
`uuidv7()` function is a fine choice for non-event-sourced tables; for our
event store it stays unused.
"""

from typing import Protocol
from uuid import UUID

import uuid_utils


class IdGenerator(Protocol):
    """Generates a fresh identifier. Same shape regardless of intended use."""

    def new_id(self) -> UUID: ...


class UUIDv7Generator:
    """Production adapter: UUIDv7 via `uuid-utils` (Rust-backed)."""

    def new_id(self) -> UUID:
        # uuid_utils.uuid7() returns a uuid_utils.UUID; convert to stdlib UUID.
        return UUID(bytes=uuid_utils.uuid7().bytes)


class FixedIdGeneratorExhaustedError(RuntimeError):
    """`FixedIdGenerator.new_id()` called more times than IDs supplied.

    A named class so a test can `pytest.raises(FixedIdGeneratorExhaustedError)`
        rather than string-matching a bare `RuntimeError`, which it still
        subclasses so a caller that pinned the original base keeps working.
    """


class FixedIdGenerator:
    """Test adapter: returns a sequence of pre-set IDs."""

    def __init__(self, ids: list[UUID]) -> None:
        self._ids = list(ids)

    def new_id(self) -> UUID:
        if not self._ids:
            msg = "FixedIdGenerator exhausted"
            raise FixedIdGeneratorExhaustedError(msg)
        return self._ids.pop(0)
