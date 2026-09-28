"""Compose the Pursuit handlers from the process-wide dependencies.

`wire_pursuit(deps)` runs once during startup and the bundle it returns is
attached to the app. Routes and MCP tools both pull their handler out of
that bundle, which is what keeps the two surfaces calling the same code
rather than two copies of it.

Wrapping order, innermost first:

  1. bind          the bare handler
  2. idempotency   a replayed key returns the first answer instead of
                   authorizing a second loop
  3. tracing       one span per call, whether or not the key hit cache

Idempotency wraps inside tracing on purpose: a cache hit is still a call
somebody made and should still appear in a trace.

The genesis takes the middle layer for the reason every genesis in this
tree does, and the stake is higher here than anywhere else it is applied.
Starting a pursuit mints an id on the server, so a retry with no key would
leave a second standing authorization nobody asked for, running its own
budget against the same beamline. A duplicated device record makes a
reporter choose; a duplicated pursuit doubles what a machine may do.

Withdrawing takes the wrapper too, and it is the only transition in this
tree that does. The argument is that a person whose stop request timed out
will send it again, and would rather be told it worked than told the
pursuit had already stopped. A 409 is the right answer to withdrawing a
pursuit that somebody else stopped; it is the wrong answer to a caller's
own retry, and only a key can tell those apart.

This slice is why the chassis can carry it. `with_idempotency` could not
wrap a handler returning None, because the store recorded a completed row
by storing a non-null result, so a stored None read back as no row: the
Postgres adapter refused the write after the events were already appended,
and the in-memory one lost the row and ran the handler again. The store
names the state in a column now, and `NOOP_SERIALIZE` and
`NOOP_DESERIALIZE` are the codec pair for a handler with nothing to
return.

So a replayed withdrawal is a second 204 rather than a 409. Withdrawing
with a different key, or none, still meets the decider and is refused,
which is the distinction the key buys.

Charging takes the wrapper, and it is the one transition in this tree that
needs it rather than merely reading better with it. Charges add to what a
pursuit has spent rather than replacing it, so a redelivered one is beam
time spent twice on a record nobody can edit. It can take the wrapper
because it answers with the new total, which is a number a reporter wants
anyway and, not coincidentally, is not None.

Opening a round goes without, and is already protected by something
better. A pursuit refuses a second round about an execution it has already
asked about, so a retry is a 409 from the domain rather than a duplicate
the chassis had to catch. Closing one is the same: a round that already
closed refuses, which matters more there than anywhere else here, because
the duplicate a retry would otherwise make is a second execution at a
beamline.

One slice takes more than the kernel. `list_pursuits` reads a projection,
which the kernel cannot hold because the kernel is declared in
infrastructure and a pursuit summary is this context's own idea, so this
module picks the implementation and passes it in.
"""

from dataclasses import dataclass
from uuid import UUID

from keeper.infrastructure.adapters.in_memory_event_store import InMemoryEventStore
from keeper.infrastructure.kernel import Kernel, UnreadableSummariesError
from keeper.infrastructure.observability import with_tracing
from keeper.infrastructure.slices.idempotency import (
    NOOP_DESERIALIZE,
    NOOP_SERIALIZE,
    with_idempotency,
)
from keeper.pursuit.adapters import (
    InMemoryPursuitSummaryLookup,
    PostgresPursuitSummaryLookup,
)
from keeper.pursuit.aggregates.pursuit.summary import PursuitSummaryLookup
from keeper.pursuit.features import (
    charge_pursuit,
    close_pursuit_round,
    get_pursuit,
    list_pursuits,
    open_pursuit_round,
    resume_pursuit,
    start_pursuit,
    withdraw_pursuit,
)

_BC = "pursuit"


@dataclass(frozen=True)
class PursuitHandlers:
    """The bundle, one field per slice."""

    start_pursuit: start_pursuit.IdempotentHandler
    open_pursuit_round: open_pursuit_round.Handler
    close_pursuit_round: close_pursuit_round.Handler
    charge_pursuit: charge_pursuit.IdempotentHandler
    resume_pursuit: resume_pursuit.Handler
    withdraw_pursuit: withdraw_pursuit.IdempotentHandler
    get_pursuit: get_pursuit.Handler
    list_pursuits: list_pursuits.Handler


def _pursuit_summary_lookup(deps: Kernel) -> PursuitSummaryLookup:
    """Pick the read adapter this deployment can actually use.

    With a pool, the projection table, which a background worker keeps in
    step. Without one, a fold over every pursuit stream, because the worker
    does not run when there is nothing to project into and an empty table
    would answer "nothing is authorized here" to somebody standing at a
    beamline where a loop is running.
    """
    if deps.pool is not None:
        return PostgresPursuitSummaryLookup(deps.pool)
    if isinstance(deps.event_store, InMemoryEventStore):
        return InMemoryPursuitSummaryLookup(deps.event_store)
    raise UnreadableSummariesError(type(deps.event_store).__name__)


def wire_pursuit(deps: Kernel) -> PursuitHandlers:
    """Build the Pursuit handlers."""
    return PursuitHandlers(
        start_pursuit=with_tracing(
            with_idempotency(
                start_pursuit.bind(deps),
                deps.idempotency_store,
                command_name="StartPursuit",
                serialize_result=str,
                deserialize_result=lambda raw: UUID(str(raw)),
                lock_stale_seconds=deps.settings.idempotency_lock_stale_seconds,
            ),
            command_name="StartPursuit",
            bc=_BC,
        ),
        open_pursuit_round=with_tracing(
            open_pursuit_round.bind(deps),
            command_name="OpenPursuitRound",
            bc=_BC,
        ),
        close_pursuit_round=with_tracing(
            close_pursuit_round.bind(deps),
            command_name="ClosePursuitRound",
            bc=_BC,
        ),
        resume_pursuit=with_tracing(
            resume_pursuit.bind(deps),
            command_name="ResumePursuit",
            bc=_BC,
        ),
        charge_pursuit=with_tracing(
            with_idempotency(
                charge_pursuit.bind(deps),
                deps.idempotency_store,
                command_name="ChargePursuit",
                serialize_result=int,
                deserialize_result=lambda raw: int(str(raw)),
                lock_stale_seconds=deps.settings.idempotency_lock_stale_seconds,
            ),
            command_name="ChargePursuit",
            bc=_BC,
        ),
        withdraw_pursuit=with_tracing(
            with_idempotency(
                withdraw_pursuit.bind(deps),
                deps.idempotency_store,
                command_name="WithdrawPursuit",
                serialize_result=NOOP_SERIALIZE,
                deserialize_result=NOOP_DESERIALIZE,
                lock_stale_seconds=deps.settings.idempotency_lock_stale_seconds,
            ),
            command_name="WithdrawPursuit",
            bc=_BC,
        ),
        get_pursuit=with_tracing(
            get_pursuit.bind(deps),
            command_name="GetPursuit",
            bc=_BC,
        ),
        list_pursuits=with_tracing(
            list_pursuits.bind(deps, _pursuit_summary_lookup(deps)),
            command_name="ListPursuits",
            bc=_BC,
        ),
    )


__all__ = ["PursuitHandlers", "wire_pursuit"]
