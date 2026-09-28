"""Withdraw the pursuit: authorize, load, decide, append at the version folded.

The version is the whole of what keeps two people stopping one pursuit
from writing two accounts of who stopped it. Both fold the same running
state, both append at the same version, and the store lets one through.
"""

from typing import Protocol
from uuid import UUID

from keeper.infrastructure.kernel import Kernel
from keeper.infrastructure.logging import get_logger
from keeper.infrastructure.ports import Deny
from keeper.infrastructure.slices.envelope import to_new_event
from keeper.pursuit.aggregates.pursuit import (
    PURSUIT_STREAM_TYPE,
    PursuitNotFoundError,
    load_pursuit_with_version,
    to_payload,
)
from keeper.pursuit.features.withdraw_pursuit.command import WithdrawPursuit
from keeper.pursuit.features.withdraw_pursuit.decider import decide
from keeper.shared.reserved_ids import NIL_SENTINEL_ID
from keeper.shared.unauthorized import UnauthorizedError

_COMMAND_NAME = "WithdrawPursuit"

_log = get_logger(__name__)


class Handler(Protocol):
    """The bare handler, before the wrapping the wire module applies."""

    async def __call__(
        self,
        command: WithdrawPursuit,
        *,
        principal_id: UUID,
        correlation_id: UUID,
        causation_id: UUID | None = None,
        surface_id: UUID = NIL_SENTINEL_ID,
    ) -> None: ...


class IdempotentHandler(Protocol):
    """The same handler once the idempotency wrapper is around it.

    One extra keyword. None means behave exactly like the bare handler,
    which is what every caller without a retry key gets.
    """

    async def __call__(
        self,
        command: WithdrawPursuit,
        *,
        principal_id: UUID,
        correlation_id: UUID,
        causation_id: UUID | None = None,
        surface_id: UUID = NIL_SENTINEL_ID,
        idempotency_key: str | None = None,
    ) -> None: ...


def bind(deps: Kernel) -> Handler:
    """Build the handler, closed over the process-wide dependencies."""

    async def handler(
        command: WithdrawPursuit,
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
                "withdraw_pursuit.denied",
                command_name=_COMMAND_NAME,
                pursuit_id=str(command.pursuit_id),
                principal_id=str(principal_id),
                correlation_id=str(correlation_id),
                reason=decision.reason,
            )
            raise UnauthorizedError(decision.reason)

        pursuit, version = await load_pursuit_with_version(deps.event_store, command.pursuit_id)
        if pursuit is None:
            raise PursuitNotFoundError(command.pursuit_id)

        events = decide(pursuit, command, actor_id=principal_id, now=deps.clock.now())

        await deps.event_store.append(
            PURSUIT_STREAM_TYPE,
            command.pursuit_id,
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
            "withdraw_pursuit.success",
            command_name=_COMMAND_NAME,
            pursuit_id=str(command.pursuit_id),
            started_by=str(pursuit.actor_id),
            principal_id=str(principal_id),
            correlation_id=str(correlation_id),
        )

    return handler


__all__ = ["Handler", "IdempotentHandler", "bind"]
