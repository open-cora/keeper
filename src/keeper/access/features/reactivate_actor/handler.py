"""Run the reactivation: authorize, load, decide, append.

Update-style, and the same shape as the deactivating handler: load and
fold, decide, then append at the version that was read, so a caller
holding a stale fold loses to whoever got there first.

No idempotency wrapper, for the same reason as its inverse. A replayed
reactivation is refused by the domain.
"""

from typing import Protocol
from uuid import UUID

from keeper.access.aggregates.actor import (
    ACTOR_STREAM_TYPE,
    load_actor_with_version,
    to_payload,
)
from keeper.access.errors import UnauthorizedError
from keeper.access.features.reactivate_actor.command import ReactivateActor
from keeper.access.features.reactivate_actor.decider import decide
from keeper.infrastructure.kernel import Kernel
from keeper.infrastructure.logging import get_logger
from keeper.infrastructure.ports import Deny
from keeper.infrastructure.slices.envelope import to_new_event
from keeper.shared.reserved_ids import NIL_SENTINEL_ID

_COMMAND_NAME = "ReactivateActor"

_log = get_logger(__name__)


class Handler(Protocol):
    """The bare handler, before the wrapping the wire module applies."""

    async def __call__(
        self,
        command: ReactivateActor,
        *,
        principal_id: UUID,
        correlation_id: UUID,
        causation_id: UUID | None = None,
        surface_id: UUID = NIL_SENTINEL_ID,
    ) -> None: ...


def bind(deps: Kernel) -> Handler:
    """Build the handler, closed over the process-wide dependencies."""

    async def handler(
        command: ReactivateActor,
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
                "reactivate_actor.denied",
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
            "reactivate_actor.success",
            command_name=_COMMAND_NAME,
            actor_id=str(command.actor_id),
            principal_id=str(principal_id),
            correlation_id=str(correlation_id),
        )

    return handler


__all__ = ["Handler", "bind"]
