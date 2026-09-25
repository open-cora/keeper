"""Projection-worker framework.

Public concepts:

  - `Projection` Protocol: the read-side fold a BC writes to maintain
    a `proj_<bc>_<name>` queryable table from the event stream. Per
    BC, lives in `aroc.<bc>.projections.<name>`. Fast, batch large
    (`batch_size=100`), idempotent at the SQL layer.

  - `Reaction` Protocol: side-effecting Subscriber that emits NEW
    events (often cross-BC) or calls the outside world. No context has
    written one; when one does it belongs in `aroc.<bc>.subscribers`.
    Slow, batch small (`batch_size=1`), idempotent via deterministic
    UUIDv5 stream id + ConcurrencyError-as-no-op. A wedged bookmark has
    no operator slice behind it here: recovery means advancing the
    bookmark row by hand.

  - `ProjectionRegistry`: the worker iterates this. Each BC registers
    its projections via `register_<bc>_projections(registry, deps)`,
    called by the composition root during lifespan setup. Execution and
    Custody make that call; Access and Authority hold no projection. The
    reaction half, `register_<bc>_subscribers(registry, deps)`, is the
    same shape and is called by nobody yet. The class name is historical;
    the registry accepts any Subscriber (Projection or Reaction).

  - `projection_worker_lifespan(deps, registry, settings)`: async
    context manager the FastAPI lifespan wraps. Spawns the worker
    when the registry is non-empty + a Postgres pool is available;
    no-ops in the in-memory test environment.

  - `drain_projections(pool, registry, deadline_seconds)`: integration-
    test helper that synchronously advances every registered subscriber
    until each bookmark catches up to the head position (or raises
    `ProjectionDrainTimeoutError`). Avoids `asyncio.sleep` flakiness.

  - `encode_cursor` / `decode_cursor`: opaque base64 round-trip for
    `(created_at, UUID)` keyset-pagination cursors. The convention:
    every `proj_*` table includes both columns and every list endpoint
    uses these helpers, so cursor format is uniform across BCs.

Internal primitive: `Subscriber` Protocol that both Projection and
Reaction satisfy structurally. Not exported publicly because BC
authors should write Projections or Reactions, not bare Subscribers.
"""

from keeper.infrastructure.projection.cursor import (
    InvalidCursorError,
    decode_cursor,
    encode_cursor,
)
from keeper.infrastructure.projection.drain import (
    ProjectionDrainTimeoutError,
    drain_projections,
)
from keeper.infrastructure.projection.lifespan import projection_worker_lifespan
from keeper.infrastructure.projection.registry import (
    DuplicateProjectionError,
    EmptySubscriptionError,
    ProjectionRegistry,
)
from keeper.infrastructure.projection.subscriber import Projection, Reaction

__all__ = [
    "DuplicateProjectionError",
    "EmptySubscriptionError",
    "InvalidCursorError",
    "Projection",
    "ProjectionDrainTimeoutError",
    "ProjectionRegistry",
    "Reaction",
    "decode_cursor",
    "drain_projections",
    "encode_cursor",
    "projection_worker_lifespan",
]
