"""Structlog processor that injects the active span's trace context.

Added to the structlog wrapper chain in `keeper.infrastructure.logging`
so every log line emitted inside an active span carries `trace_id`,
`span_id`, and `trace_flags`: letting log-aggregator queries pivot
from a log line to the corresponding distributed trace.

When no span is active (no-op tracer in tests, or code paths invoked
outside an instrumented entrypoint), the processor is a no-op: it
returns the event_dict unchanged. No keys are added rather than
`None`-valued keys, which keeps log lines compact and avoids polluting
indexed fields with sentinel values.

`trace_id` is rendered as a 32-char lowercase hex string (W3C trace
context format), matching what OTel exporters write to spans.
`span_id` is the 16-char span hex.
"""

from collections.abc import MutableMapping
from typing import Any

from opentelemetry import trace
from opentelemetry.trace import INVALID_SPAN_ID, INVALID_TRACE_ID

# structlog's Processor signature is (WrappedLogger, str, EventDict)
# where EventDict is `MutableMapping[str, Any]`. We type-match exactly
# rather than depend on `structlog.types.EventDict` so this module
# stays free of structlog imports (it's a pure function consumed by
# the structlog wrapper chain in `keeper.infrastructure.logging`).
EventDict = MutableMapping[str, Any]

__all__ = ["add_trace_context"]


def add_trace_context(_logger: Any, _method_name: str, event_dict: EventDict) -> EventDict:
    """Inject trace_id/span_id/trace_flags from the active span, if any."""
    span_context = trace.get_current_span().get_span_context()
    if span_context.trace_id == INVALID_TRACE_ID:
        return event_dict
    event_dict["trace_id"] = format(span_context.trace_id, "032x")
    if span_context.span_id != INVALID_SPAN_ID:
        event_dict["span_id"] = format(span_context.span_id, "016x")
    event_dict["trace_flags"] = format(span_context.trace_flags, "02x")
    return event_dict
