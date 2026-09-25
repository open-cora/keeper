"""Infrastructure ports: the `Protocol` seams every side effect goes through.

A port names a capability the domain needs without naming a technology. The
domain layer imports the Protocol; the composition root binds an adapter to
it. That inversion is what keeps deciders pure and lets the whole suite run
against in-memory implementations.

Two families live here, and only one has members:

  - **Infrastructure seams**: `Clock`, `IdGenerator`, `EventStore`,
    `IdempotencyStore`, `Authorize`, `TokenVerifier`.
    These are technology seams: the capability is generic and the adapter
    picks the substrate.
  - **Cross-BC lookups**: a `<Thing>Lookup` Protocol declared here,
    implemented by the owning BC's adapter, and consumed by a sibling BC
    that must not import it directly. Still none, and no longer for want of
    bounded contexts: there are four.

Read that second family as a warning as much as an invitation. A lookup port
declared in this shared namespace creates a real dependency between two BCs
while leaving no import for `tach.toml` to constrain: both sides name only
`keeper.infrastructure`, which every module does.

What the contexts produced instead is a set of read ports that are not
cross-BC at all. `ExecutionSummaryLookup`, `PlanSummaryLookup` and
`DatasetSummaryLookup` are each declared beside the aggregate they summarize,
in that context's own summary module, and each is consumed only by the
context that declares it.

That is evidence about the local case and not about this one. A port with one
context on both ends has no reason to sit in a shared namespace, and the
question this paragraph used to defer to the first contexts that needed one
is still open for a port with a sibling on the far end. `Kernel`'s docstring
carries what such a port would have to decide about its default.
"""

from keeper.infrastructure.ports.authorize import (
    Allow,
    AllowAllAuthorize,
    Authorize,
    Deny,
)
from keeper.infrastructure.ports.clock import (
    Clock,
    FakeClock,
    FakeMonotonicClock,
    MonotonicClock,
    SystemClock,
    SystemMonotonicClock,
)
from keeper.infrastructure.ports.event_store import (
    ConcurrencyError,
    EventStore,
    NewEvent,
    StoredEvent,
    StreamAppend,
)
from keeper.infrastructure.ports.id_generator import (
    FixedIdGenerator,
    FixedIdGeneratorExhaustedError,
    IdGenerator,
    UUIDv7Generator,
)
from keeper.infrastructure.ports.idempotency_store import (
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
from keeper.infrastructure.ports.token_verifier import (
    IntrospectionUnavailableError,
    InvalidTokenError,
    PrincipalKind,
    SubjectMapper,
    TokenVerifier,
    VerifiedPrincipal,
)

__all__ = [
    "Allow",
    "AllowAllAuthorize",
    "Authorize",
    "CachedError",
    "CachedHandlerError",
    "CachedSuccess",
    "Claimed",
    "Clock",
    "ConcurrencyError",
    "Deny",
    "EventStore",
    "FakeClock",
    "FakeMonotonicClock",
    "FixedIdGenerator",
    "FixedIdGeneratorExhaustedError",
    "HashConflict",
    "IdGenerator",
    "IdempotencyClaimLostError",
    "IdempotencyConflictError",
    "IdempotencyStore",
    "IntrospectionUnavailableError",
    "InvalidTokenError",
    "LockedRecent",
    "MonotonicClock",
    "NewEvent",
    "PrincipalKind",
    "StoredEvent",
    "StreamAppend",
    "SubjectMapper",
    "SystemClock",
    "SystemMonotonicClock",
    "TokenVerifier",
    "UUIDv7Generator",
    "VerifiedPrincipal",
]
