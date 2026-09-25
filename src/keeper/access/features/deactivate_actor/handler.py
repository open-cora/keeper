"""Run the deactivation: authorize, load, decide, append.

Update-style shape, and the first one here. Unlike registering, this
command names an actor that may already have a history, so the handler
loads and folds that history before deciding and passes the version it
read back as `expected_version`.

That version is the whole of the concurrency story. Two callers
deactivating the same actor at once both fold the same state and both
decide to append at the same version; the store lets one through and
raises `ConcurrencyError` at the other, which surfaces as a 409. Without
it the second append would land as a second deactivation of an actor
already inactive, which the decider exists to refuse.

No idempotency wrapper, unlike registering. A replayed deactivation is
already refused by the domain, so the wrapper would be buying a nicer
status code for a retry rather than preventing a duplicate. See the
wiring module, which says which layers a slice gets and why.
"""

from typing import Protocol
from uuid import UUID

from keeper.access.aggregates.actor import (
    ACTOR_STREAM_TYPE,
    load_actor_with_version,
    to_payload,
)
from keeper.access.errors import UnauthorizedError
from keeper.access.features.deactivate_actor.command import DeactivateActor
from keeper.access.features.deactivate_actor.decider import decide
from keeper.infrastructure.kernel import Kernel
from keeper.infrastructure.logging import get_logger
from keeper.infrastructure.ports import Deny
from keeper.infrastructure.slices.envelope import to_new_event
from keeper.shared.reserved_ids import NIL_SENTINEL_ID

_COMMAND_NAME = "DeactivateActor"

_log = get_logger(__name__)


class Handler(Protocol):
    """The bare handler, before the wrapping the wire module applies."""

    async def __call__(
        self,
        command: DeactivateActor,
        *,
        principal_id: UUID,
        correlation_id: UUID,
        causation_id: UUID | None = None,
        surface_id: UUID = NIL_SENTINEL_ID,
    ) -> None: ...


def bind(deps: Kernel) -> Handler:
    """Build the handler, closed over the process-wide dependencies."""

    async def handler(
        command: DeactivateActor,
        *,
        principal_id: UUID,
        correlation_id: UUID,
        causation_id: UUID | None = None,
        surface_id: UUID = NIL_SENTINEL_ID,
    ) -> None:
        decision = await deps.authz.authorize(
            principal_id=principal_id,
            command_name=_COMMAND_NAME,
            surface_id=surface_id,
        )
        if isinstance(decision, Deny):
            _log.info(
                "deactivate_actor.denied",
                command_name=_COMMAND_NAME,
                actor_id=str(command.actor_id),
                principal_id=str(principal_id),
                correlation_id=str(correlation_id),
                reason=decision.reason,
            )
            raise UnauthorizedError(decision.reason)

        state, version = await load_actor_with_version(deps.event_store, command.actor_id)
        now = deps.clock.now()
        events = decide(state, command, now=now)

        await deps.event_store.append(
            ACTOR_STREAM_TYPE,
            command.actor_id,
            version,
            [
                to_new_event(
                    event_type=type(event).__name__,
                    payload=to_payload(event),
                    occurred_at=event.occurred_at,
                    event_id=deps.id_generator.new_id(),
                    command_name=_COMMAND_NAME,
                    correlation_id=correlation_id,
                    causation_id=causation_id,
                    principal_id=principal_id,
                )
                for event in events
            ],
        )

        _log.info(
            "deactivate_actor.success",
            command_name=_COMMAND_NAME,
            actor_id=str(command.actor_id),
            principal_id=str(principal_id),
            correlation_id=str(correlation_id),
        )

    return handler


__all__ = ["Handler", "bind"]
