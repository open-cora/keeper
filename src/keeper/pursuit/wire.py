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

Withdrawing goes without, beside every other transition in this tree, and
it was wired with the wrapper first. The argument for it was that a person
whose stop request timed out will send it again and would rather be told
it worked than told the pursuit had already stopped. That argument is real
and it is not worth what answering it currently costs.

`with_idempotency` cannot carry a handler that returns None. A stored
result of None is indistinguishable from no stored result, so the replay
reads as a fresh claim, runs the handler again and caches the refusal it
raises. Nothing else in this tree returns None through the wrapper, so the
limitation had never been reached; withdrawing reached it. Making it work
means changing the store on both adapters and the constraint behind them,
which is a change to shared infrastructure and does not belong in the
commit that adds a context.

So a replayed withdrawal is a 409, which is what a replayed transition is
everywhere else here, and the contract tier says so out loud rather than
leaving it to be discovered.

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

No slice takes more than the kernel. Nothing here reads a projection,
because nothing here lists anything yet.
"""

from dataclasses import dataclass
from uuid import UUID

from keeper.infrastructure.kernel import Kernel
from keeper.infrastructure.observability import with_tracing
from keeper.infrastructure.slices.idempotency import with_idempotency
from keeper.pursuit.features import (
    charge_pursuit,
    close_pursuit_round,
    get_pursuit,
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
    withdraw_pursuit: withdraw_pursuit.Handler
    get_pursuit: get_pursuit.Handler


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
            withdraw_pursuit.bind(deps),
            command_name="WithdrawPursuit",
            bc=_BC,
        ),
        get_pursuit=with_tracing(
            get_pursuit.bind(deps),
            command_name="GetPursuit",
            bc=_BC,
        ),
    )


__all__ = ["PursuitHandlers", "wire_pursuit"]
