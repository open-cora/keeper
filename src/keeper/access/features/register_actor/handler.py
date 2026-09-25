"""Run the registration: authorize, decide, append.

Create-style shape. A freshly minted id provably has no history, so this
handler skips the load-and-fold that an update-style handler starts with
and hands `state=None` straight to the decider.

One store is written, so there is no ordering to get right and no window
in which a crash leaves two stores disagreeing about the same actor. The
append either lands or it does not.
"""

from typing import Protocol
from uuid import UUID

from keeper.access.aggregates.actor import ACTOR_STREAM_TYPE, to_payload
from keeper.access.errors import UnauthorizedError
from keeper.access.features.register_actor.command import RegisterActor
from keeper.access.features.register_actor.decider import decide
from keeper.infrastructure.kernel import Kernel
from keeper.infrastructure.logging import get_logger
from keeper.infrastructure.ports import Deny
from keeper.infrastructure.slices.envelope import to_new_event
from keeper.shared.reserved_ids import NIL_SENTINEL_ID

_COMMAND_NAME = "RegisterActor"

_log = get_logger(__name__)


class Handler(Protocol):
    """The bare handler, before the wrapping the wire module applies.

    `causation_id` is the id of whatever triggered this command, when
    something did. An HTTP or MCP call is the root of its own chain and
    passes None; a future reaction to an event passes that event's id.
    """

    async def __call__(
        self,
        command: RegisterActor,
        *,
        principal_id: UUID,
        correlation_id: UUID,
        causation_id: UUID | None = None,
        surface_id: UUID = NIL_SENTINEL_ID,
    ) -> UUID: ...


class IdempotentHandler(Protocol):
    """The same handler once the idempotency wrapper is around it.

    One extra keyword. None means behave exactly like the bare handler,
    which is what every caller without a retry key gets.
    """

    async def __call__(
        self,
        command: RegisterActor,
        *,
        principal_id: UUID,
        correlation_id: UUID,
        causation_id: UUID | None = None,
        surface_id: UUID = NIL_SENTINEL_ID,
        idempotency_key: str | None = None,
    ) -> UUID: ...


def bind(deps: Kernel) -> Handler:
    """Build the handler, closed over the process-wide dependencies."""

    async def handler(
        command: RegisterActor,
        *,
        principal_id: UUID,
        correlation_id: UUID,
        causation_id: UUID | None = None,
        surface_id: UUID = NIL_SENTINEL_ID,
    ) -> UUID:
        decision = await deps.authz.authorize(
            principal_id=principal_id,
            command_name=_COMMAND_NAME,
            surface_id=surface_id,
        )
        if isinstance(decision, Deny):
            _log.info(
                "register_actor.denied",
                command_name=_COMMAND_NAME,
                principal_id=str(principal_id),
                correlation_id=str(correlation_id),
                reason=decision.reason,
            )
            raise UnauthorizedError(decision.reason)

        new_id = deps.id_generator.new_id()
        now = deps.clock.now()
        events = decide(None, command, now=now, new_id=new_id)

        await deps.event_store.append(
            ACTOR_STREAM_TYPE,
            new_id,
            0,
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
            "register_actor.success",
            command_name=_COMMAND_NAME,
            actor_id=str(new_id),
            principal_id=str(principal_id),
            correlation_id=str(correlation_id),
        )
        return new_id

    return handler


__all__ = ["Handler", "IdempotentHandler", "bind"]
