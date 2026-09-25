"""Composition wrapper that traces a command or query handler call.

`with_tracing(handler, *, command_name, bc, kind)` returns a callable
with the same signature as `handler`, wrapped in a span named
`<bc>.<kind>.<command_name>`. On exception the OTel SDK's span
context-manager `__exit__` records the exception event and sets
status ERROR with description `<ExcType>: <message>` automatically
(both behaviors are SDK defaults: `record_exception=True` and
`set_status_on_exception=True` on `start_as_current_span`). The
wrapper deliberately does NOT call `record_exception` or `set_status`
itself, doing so would either duplicate the exception event or
fight the SDK over the description.

Composition order at the wiring site (innermost first): tracing wraps
idempotency wraps the bare handler, so cache hits, cache misses, and
domain failures all attribute to the tracing span correctly.

Span attributes use the `aroc.*` namespace for project-specific
metadata (`keeper.bc`, `keeper.command`, `keeper.query`, `keeper.principal_id`);
HTTP / DB / messaging attributes come from the underlying
instrumentations. `keeper.principal_id` is sniffed from kwargs since
every handler in AROC takes `principal_id: UUID` as a keyword arg
(per the cross-BC handler-call convention). When present, the value
is recorded so trace queries can filter "everything principal X did
in this trace", aligning with the 2026 multi-agent identity audit
practice (EU AI Act Article 12, SOC 2 CC7.2).

Cached-hit semantics: tracing wraps idempotency, so the
`keeper.principal_id` attribute is set BEFORE the inner idempotency
wrapper decides whether to invoke the bare handler or return a
cached result. This is intentional: the trace records "principal X
attempted command Y, got cached result Z" even when no event is
written to the store. Trace queries that count "principal X's
distinct command attempts" remain accurate under retry.

Strict-accuracy footnote: the attribute is set when `principal_id`
is non-None in the kwargs. Under production posture
(`Settings.require_authenticated_principal=True`), the auth proxy
guarantees a real UUID on every request so this is always the case.
Under dev/test posture the fallback `SYSTEM_PRINCIPAL_ID` is also a
real UUID, so the attribute still lands. The `None`-omission branch
exists only as defensive code for hypothetical future call shapes
that pass no kwarg at all.
"""

from typing import Any, Literal, Protocol

from opentelemetry import trace
from opentelemetry.trace import SpanKind

Kind = Literal["command", "query"]

# One tracer for the whole application, named for the application. Naming it
# after whichever bounded context reached for this decorator first would put
# that accident in the scope of every span the process emits, and span names
# already carry the BC as their first segment.
_tracer = trace.get_tracer("keeper")


class _AsyncHandler[**P, R](Protocol):
    """Structural type for any async callable.

    Defined as a Protocol with `async def __call__` so the wrapped
    handler returned by `with_tracing` is assignable to slice handler
    Protocols (`register_actor.IdempotentHandler` et al.), which are
    themselves `async def __call__` Protocols. Typing with
    `Callable[P, Coroutine[...]]` doesn't work here: pyright resolves
    `async def __call__` Protocol methods to `CoroutineType`-returning,
    which `Coroutine` is not assignable to even though the runtime
    objects are interchangeable.
    """

    async def __call__(self, *args: P.args, **kwargs: P.kwargs) -> R: ...


def with_tracing[**P, R](
    handler: _AsyncHandler[P, R],
    *,
    command_name: str,
    bc: str,
    kind: Kind = "command",
) -> _AsyncHandler[P, R]:
    """Wrap an async handler with an OTel span around the call.

    `bc` and `command_name` are recorded as `keeper.bc` and `keeper.command`
    (or `keeper.query` when `kind="query"`) attributes for trace-side
    filtering. The span name follows `<bc>.<kind>.<command_name>` so
    traces group naturally by bounded context in the UI.
    """
    span_name = f"{bc}.{kind}.{command_name}"
    name_attr = f"keeper.{kind}"

    async def wrapped(*args: P.args, **kwargs: P.kwargs) -> R:
        attributes: dict[str, Any] = {
            "keeper.bc": bc,
            name_attr: command_name,
        }
        principal_id = kwargs.get("principal_id")
        if principal_id is not None:
            attributes["keeper.principal_id"] = str(principal_id)
        with _tracer.start_as_current_span(
            span_name,
            kind=SpanKind.INTERNAL,
            attributes=attributes,
        ):
            return await handler(*args, **kwargs)

    return wrapped


__all__ = ["Kind", "with_tracing"]
