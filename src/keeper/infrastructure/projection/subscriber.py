"""Projection + Reaction Protocols, both satisfying the internal Subscriber primitive.

Two public kinds of Subscriber:

  - `Projection`: read-side fold of an event stream into a queryable
    `proj_*` table. Fast (sub-millisecond apply), batches large
    (`batch_size=100` default), idempotent at the SQL layer
    (`ON CONFLICT`). Failure mode: stale read model until next poll.

  - `Reaction`: side-effecting consumer that produces NEW events
    (often cross-BC) or calls the outside world (LLMs, storage,
    signers). Slow (LLM-bounded, 5-15 s apply), batches small
    (`batch_size=1` recommended), idempotent via deterministic
    UUIDv5 stream ids + `expected_version=0` + `ConcurrencyError`-
    as-no-op. Failure mode: wedged bookmark on poison event;
    recoverable only by advancing the bookmark row by hand, there
    being no operator slice for it here.

`Subscriber` is the framework-internal primitive the worker advances
along the event stream; both Projection and Reaction satisfy it via
structural typing. The worker iterates Subscribers without caring
which kind they are; per-subscriber `batch_size` lets each kind tune
its own throughput vs latency tradeoff.

The Protocols are structurally identical today (same field set, same
callable shape). The split is operational, not type-theoretic: it
documents the two distinct failure-and-tuning regimes a BC author is
opting into.
"""

from typing import Any, Protocol, runtime_checkable

from keeper.infrastructure.ports.event_store import StoredEvent

# `Any` for the connection argument because asyncpg's `pool.acquire()`
# yields `PoolConnectionProxy`, not `Connection` directly, and pyright
# narrows the union loosely. The proxy delegates to Connection at
# runtime so the interface (.execute / .fetch / .transaction / etc.)
# behaves identically. Existing Postgres adapters in this codebase
# adopt the same pattern.
ConnectionLike = Any

# Worker-level default batch size when a Subscriber declines to
# declare its own. Projections inherit this implicitly; Reactions
# should override to 1 (slow LLM call should not hold a pool
# connection across N events).
DEFAULT_BATCH_SIZE = 100


@runtime_checkable
class Subscriber(Protocol):
    """Internal framework primitive: anything the projection worker
    advances along the event stream via a bookmark.

    Not exported publicly as a vocabulary BC authors write against;
    they write Projections or Reactions. Both satisfy this Protocol
    via structural typing.

    `name`, `subscribed_event_types`, and `batch_size` are declared
    as plain attrs (not ClassVar) so test fixtures can construct
    varying instances inline. Production subscribers typically
    declare them as class-level constants since they're immutable
    per subscriber, that satisfies this Protocol via structural
    typing.

    `batch_size` is intentionally NOT on the Subscriber Protocol so
    the 14 existing Projections that pre-date the per-subscriber knob
    continue to satisfy the contract without a sweeping update. The
    worker reads `getattr(subscriber, "batch_size", DEFAULT_BATCH_SIZE)`
    so a Subscriber that omits the attribute inherits the default
    transparently. The Reaction Protocol DOES require `batch_size`
    because Reactions must opt into the slow-batch-1 regime explicitly.
    """

    name: str
    subscribed_event_types: frozenset[str]

    async def apply(
        self,
        event: StoredEvent,
        conn: ConnectionLike,
    ) -> None: ...


@runtime_checkable
class Projection(Protocol):
    """Read-side fold of an event stream into a queryable `proj_*` table.

    A BC's projection lives at `keeper.<bc>.projections.<name>` and is
    registered via `register_<bc>_projections(registry, deps)`. The
    framework owns advance, bookmarking, and at-least-once delivery;
    the projection owns the `apply` logic and the schema of its
    `proj_<bc>_<name>` table.

    Contract:

      - `name` MUST match the projection's `proj_*` table name AND
        the bookmark row inserted in the projection's migration.
        This is the key the worker uses to look up the bookmark
        (`projection_bookmarks.name = self.name`). The three have to
        agree and nothing checks that they do; the convention is what
        makes a check possible once a projection exists to check.

      - `subscribed_event_types` is the set of `event_type` strings the
        projection cares about. The advance query pushes the predicate
        down to SQL (`event_type = ANY($subscribed)`); events outside
        the set are never delivered to `apply`.

      - `apply` MUST be idempotent. The framework delivers at-least-
        once: under crash-restart between `apply()` and bookmark
        update, the next batch will re-deliver the event. Standard
        patterns: `INSERT ... ON CONFLICT (key) DO NOTHING/UPDATE`,
        UPDATE-to-same-value, or any operation whose net effect is
        independent of how many times it runs. This is a requirement
        on the author, not a checked one: a scan for `ON CONFLICT` or
        for a declared marker comment would be cheap, and belongs here
        with the first projection.

      - `apply` runs INSIDE the worker's advance transaction. The
        bookmark advance + the projection writes commit together;
        if `apply` raises, the entire batch rolls back and the
        bookmark stays at its previous position so the same events
        are retried on the next iteration.

      - The connection passed to `apply` is the same connection the
        worker uses for the advance scan and the bookmark UPDATE.
        Don't acquire your own connection from the pool; use the one
        you're given.

    Operational notes:

      - Long-running transactions in the same database PAUSE all
        projections (`pg_snapshot_xmin` returns the lowest active
        xid8; events from later-started transactions become visible
        to projections only after the long transaction commits). By
        design, operational mode worth knowing. Avoid `BEGIN;` in
        psql sessions while debugging projection lag.

      - The advance query orders by `(transaction_id, position)` so
        events appear in commit order across streams. Within a single
        transaction (one xid8 covering N events), order is by
        position.

      - Per-projection bookmarks mean projections advance independently
        and at their own pace. One projection lagging does not block
        others.

      - `batch_size` is intentionally NOT in the Projection Protocol.
        The worker reads `getattr(projection, "batch_size", DEFAULT_BATCH_SIZE)`
        so a Projection that overrides it (e.g., a high-throughput
        projection that wants 250) wins, and one that omits it
        inherits the default 100 transparently. Reactions, by
        contrast, MUST declare `batch_size` because the Reaction
        Protocol enforces the opt-in to the slow-apply regime.
    """

    name: str
    subscribed_event_types: frozenset[str]

    async def apply(
        self,
        event: StoredEvent,
        conn: ConnectionLike,
    ) -> None:
        """Apply a single event to the projection's read-model state.

        Idempotency is the projection author's responsibility; the
        framework will re-deliver under at-least-once semantics.
        """
        ...


@runtime_checkable
class Reaction(Protocol):
    """Side-effecting Subscriber: consumes events and produces NEW
    events (often into other BCs) or calls the outside world
    (LLMs, storage, signing services).

    Parallel to `Projection`; both satisfy `Subscriber`. The split
    is operational, not type-theoretic:

      - Projections are fast (sub-millisecond apply), batch large
        (`batch_size=100` default), and idempotent at the SQL layer
        (`ON CONFLICT`). Their failure mode is "stale read model
        until next poll" and the operator playbook is "wait."

      - Reactions are slow (LLM-bounded, 5-15 s apply), batch small
        (`batch_size=1` recommended), and idempotent via
        deterministic UUIDv5 stream ids + `expected_version=0` +
        `ConcurrencyError`-as-no-op. Their failure mode is "wedged
        bookmark on poison event", and no slice answers it here: an
        operator advances the bookmark row directly.

    Contract:

      - `batch_size` SHOULD be 1 unless the apply path is provably
        fast (no LLM call, no external HTTP, no signer round-trip).
        Holding a pool connection across N * 15 s LLM calls
        starves Projection advance loops sharing the same pool.

      - `apply` MUST achieve at-most-once delivery via deterministic
        stream-id derivation. Pattern: derive the side-effect's
        stream_id as `uuid5(NAMESPACE_OID, f"{name}:{event.event_id}")`
        and call `event_store.append(...,  expected_version=0)`; catch
        `ConcurrencyError` and treat as success (the side effect was
        already applied on a previous attempt).

      - `apply` runs INSIDE the worker's advance transaction. The
        bookmark advance + any conn-bound writes commit together; if
        `apply` raises, the entire batch rolls back and the bookmark
        stays at its previous position so the same events are retried
        on the next iteration.

      - Cross-BC `EventStore.append` calls inside `apply` use a
        SEPARATE pool connection from the advance loop's connection.
        Cross-TX writes are unavoidable for cross-BC side effects;
        the UUIDv5 + ConcurrencyError pattern absorbs the resulting
        at-least-once retries.

      - The cross-BC append cannot be rolled back if the bookmark
        update later fails. Reactions writing to multiple BC streams
        in one `apply` accept this asymmetry by design: the side
        effect is recorded; the worker re-fires; the second attempt
        is absorbed by ConcurrencyError.

    Operational notes:

      - Wedge recovery: if `apply` raises a non-recoverable error
        (poison event, schema drift, deserialization failure), the
        bookmark stays put and `consecutive_failures` increments on
        each retry. Operator response: advance the bookmark row past
        the poison event by hand. No slice does this here, so the move
        leaves no auditable record of itself.

      - Today every Reaction runs in the same pool as Projections.
        Watch-item: when a third Reaction lands OR the first wedge
        incident occurs, split off a dedicated reaction worker with its own
        pool budget.
    """

    name: str
    subscribed_event_types: frozenset[str]
    batch_size: int

    async def apply(
        self,
        event: StoredEvent,
        conn: ConnectionLike,
    ) -> None:
        """Apply a single event by emitting NEW events or calling
        the outside world.

        At-most-once delivery is the Reaction author's responsibility
        (deterministic UUIDv5 stream id + ConcurrencyError catch);
        the framework delivers at-least-once.
        """
        ...


__all__ = ["DEFAULT_BATCH_SIZE", "ConnectionLike", "Projection", "Reaction", "Subscriber"]
