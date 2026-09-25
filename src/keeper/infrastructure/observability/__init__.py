"""OpenTelemetry wiring and helpers.

Public surface for the rest of the codebase:

- `configure_tracing(settings)`: call once at startup; returns a
  teardown callable that flushes pending spans on shutdown.
- `current_correlation_id()`: derive the request's correlation UUID
  from the active OTel span's trace_id. Used by REST route dependencies
  and MCP tool entrypoints; replaces the prior `asgi-correlation-id`-
  based source.
- `with_tracing(handler, *, command_name, kind)`: composition wrapper
  applied in each BC's wiring module. Adds a span around each command /
  query handler call, sets `keeper.*` attributes, records exceptions.
- `add_trace_context`: structlog processor that injects `trace_id`
  and `span_id` into every log line emitted inside an active span.

Domain and application code never imports OpenTelemetry directly; it
imports from this package, so the choice of telemetry library is local
to one folder and swappable.
"""

from keeper.infrastructure.observability.correlation import current_correlation_id
from keeper.infrastructure.observability.log_processor import add_trace_context
from keeper.infrastructure.observability.span import with_tracing
from keeper.infrastructure.observability.tracing import (
    Teardown,
    build_tracing,
    configure_tracing,
    instrument_app,
)

__all__ = [
    "Teardown",
    "add_trace_context",
    "build_tracing",
    "configure_tracing",
    "current_correlation_id",
    "instrument_app",
    "with_tracing",
]
