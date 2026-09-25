"""Compose the Access handlers from the process-wide dependencies.

`wire_access(deps)` runs once during startup and the bundle it returns is
attached to the app. Routes and MCP tools both pull their handler out of
that bundle, which is what keeps the two surfaces calling the same code
rather than two copies of it.

Wrapping order, innermost first:

  1. bind          the bare handler
  2. idempotency   a replayed key returns the first answer instead of
                   creating a second actor
  3. tracing       one span per call, whether or not the key hit cache

Idempotency wraps inside tracing on purpose: a cache hit is still a call
somebody made and should still appear in a trace.

Not every slice wants the middle layer. Both switch slices go without
it: a replayed deactivation or reactivation is already refused by the
domain, so the wrapper would be buying a friendlier status code for a
retry rather than preventing a second write. `get_actor` goes without it
because a read has nothing to make idempotent.

Tracing wraps every slice, reads included. A query that is slow or
failing is as much a fact about the system as a write that is.
"""

from dataclasses import dataclass
from uuid import UUID

from keeper.access.features import deactivate_actor, get_actor, reactivate_actor, register_actor
from keeper.infrastructure.kernel import Kernel
from keeper.infrastructure.observability import with_tracing
from keeper.infrastructure.slices.idempotency import with_idempotency

_BC = "access"


@dataclass(frozen=True)
class AccessHandlers:
    """The bundle, one field per slice."""

    register_actor: register_actor.IdempotentHandler
    deactivate_actor: deactivate_actor.Handler
    reactivate_actor: reactivate_actor.Handler
    get_actor: get_actor.Handler


def wire_access(deps: Kernel) -> AccessHandlers:
    """Build the Access handlers."""
    return AccessHandlers(
        register_actor=with_tracing(
            with_idempotency(
                register_actor.bind(deps),
                deps.idempotency_store,
                command_name="RegisterActor",
                serialize_result=str,
                deserialize_result=lambda raw: UUID(str(raw)),
                lock_stale_seconds=deps.settings.idempotency_lock_stale_seconds,
            ),
            command_name="RegisterActor",
            bc=_BC,
        ),
        deactivate_actor=with_tracing(
            deactivate_actor.bind(deps),
            command_name="DeactivateActor",
            bc=_BC,
        ),
        reactivate_actor=with_tracing(
            reactivate_actor.bind(deps),
            command_name="ReactivateActor",
            bc=_BC,
        ),
        get_actor=with_tracing(
            get_actor.bind(deps),
            command_name="GetActor",
            bc=_BC,
        ),
    )


__all__ = ["AccessHandlers", "wire_access"]
