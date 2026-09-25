"""Derive the request's correlation UUID from the active OTel span.

The event-store schema persists `correlation_id` as a `uuid` column;
the rest of the codebase types it as `UUID`. With OTel as the source
of truth for "this request" identity, the trace_id (128-bit) is
encoded into a UUID via `UUID(int=trace_id)`. Both REST routes and
MCP tool entrypoints pull the correlation id from here, so the value
in event metadata always matches the trace_id in distributed traces
(format `<trace_id_hex_with_dashes>` ↔ `UUID.hex`).

Caveat: the resulting UUID is a bit-encoding of random trace_id
bytes; the version/variant bit positions hold whatever the trace_id
generator emitted, so the UUID will not parse as a valid v4 or v7.
Storage round-trips fine (Postgres `uuid` is just 16 bytes); UUID
introspection (for example `uuid.version`) is meaningless on this value.

If no span is active (test environments using the no-op tracer, or
code paths invoked outside an instrumented entrypoint), a fresh
UUIDv4 is generated so callers always receive a well-formed UUID.
Multiple calls without a span return DIFFERENT UUIDs, not a problem
in practice because routes resolve the correlation_id once via
FastAPI Depends and pass it through, but worth knowing if a test
ever tries to assert correlation_id stability without a span.
"""

from uuid import UUID, uuid4

from opentelemetry import trace
from opentelemetry.trace import INVALID_TRACE_ID

__all__ = ["current_correlation_id"]


def current_correlation_id() -> UUID:
    """Return a UUID derived from the current OTel trace_id, or a fresh UUID."""
    span_context = trace.get_current_span().get_span_context()
    if span_context.trace_id == INVALID_TRACE_ID:
        return uuid4()
    return UUID(int=span_context.trace_id)
