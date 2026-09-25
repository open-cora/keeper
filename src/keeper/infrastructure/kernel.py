"""Process-wide dependency kernel.

`Kernel` carries the cross-BC primitives (settings, clock, id_generator,
authorize, event_store, idempotency_store) plus the asyncpg `pool`, which is
None when `app_env=test`. It is the "shared kernel" in the DDD sense: a
deliberately-shared set of dependencies every bounded context's
`wire_<bc>(deps)` function pulls from.

## Why this lives in its own module

This module has **zero BC imports**, and that is the point. Every BC's wire,
handler, and route imports `Kernel` from here without transitively pulling in
any other BC.

Anything that needs a bounded context to construct it is INJECTED into
`build_kernel` by the composition root rather than imported here. The
authorize factory is the canonical case: the real implementation lives in
whichever BC owns policy, and a lazy import from this module would be a cycle
that a dependency checker cannot see through, because the import is
control-flow-guarded.

## BC-specific stores stay BC-internal

`Kernel` carries cross-BC primitives only. A store that serves exactly one
bounded context is constructed inside that BC's own `wire_<bc>(deps)` from
`deps.pool` and lives BC-internal. This is what keeps the kernel from growing
a field per BC as the system fills in.

## What is NOT here yet

No cross-BC read port has a field here: a lookup one BC implements and a
sibling consumes. Authority does read Access, and it reaches `load_actor`
through the door tach cuts in its interfaces block rather than through
anything on this dataclass. That works while the consumer can name the
producer. A field here is what the other case needs, where the kernel has to
hand a consumer its answer without either side importing the other.

When the first one appears, note what its default says. A permissive default
(an always-satisfied lookup) keeps unrelated tests from having to seed data,
but it also means a deployment that forgot to wire the real adapter runs with
the check silently off. A `None` default that a consumer refuses to proceed
past fails loudly instead. Neither is right in general; the choice belongs to
the gate the port feeds, and it should be stated in the field's own docstring
rather than inherited by copying the field above it.
"""

from dataclasses import dataclass

import asyncpg

from keeper.infrastructure.ports import (
    Authorize,
    Clock,
    EventStore,
    IdempotencyStore,
    IdGenerator,
    TokenVerifier,
)
from keeper.infrastructure.schema import SchemaPosture
from keeper.infrastructure.settings import Settings


@dataclass(frozen=True)
class Kernel:
    """Process-wide dependencies. Immutable after construction.

    `pool` is the asyncpg connection pool, None when `app_env=test`. A BC that
    needs an additional Postgres-backed adapter (an entry store, a projection)
    constructs it in its own `wire_<bc>(deps)` from this pool, which keeps
    BC-specific stores out of the kernel.
    """

    settings: Settings
    clock: Clock
    id_generator: IdGenerator
    authz: Authorize
    event_store: EventStore
    idempotency_store: IdempotencyStore

    pool: asyncpg.Pool | None = None

    schema_posture: SchemaPosture = "matched"
    """Whether the applied database schema is the one this build expects.

    `degraded` means the process booted against a mismatched schema under an
    explicit override, and its `event_store` is a `ReadOnlyEventStore`.
    Carried here so `/readyz` can report the posture: an operator who set the
    override on one host should not have to remember they did.
    """

    token_verifier: TokenVerifier | None = None
