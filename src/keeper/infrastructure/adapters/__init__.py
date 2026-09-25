"""Cross-BC infrastructure adapters.

Implementations of the ports defined in `keeper.infrastructure.ports` that
are consumed by multiple BCs (event store, idempotency, token verification).
Naming: the filename is `snake_case(<Tech><Port>).py`, class is
`<Tech><Port>` with no `Adapter` suffix.

Most adapters here reach a real technology. `ReadOnlyEventStore` does
not: it wraps another `EventStore` and refuses its writes. It lives
here anyway, because the question this directory answers is "what
satisfies this port", and an implementation kept elsewhere makes that
question take two places to answer.
"""
