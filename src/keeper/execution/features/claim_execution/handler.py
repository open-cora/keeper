"""Claim the execution: authorize, load, decide, append.

Update-style, so the execution is loaded with its version and the append is
made against it. That version matters more here than anywhere else on
this stream: two drivers claiming one dispatch at the same instant is
exactly the race, and the expected version is what turns it into one
append and one conflict rather than two claims.
"""

from typing import Protocol
from uuid import UUID

from keeper.execution.aggregates.execution import (
    EXECUTION_STREAM_TYPE,
    load_execution_with_version,
    to_payload,
)
from keeper.execution.errors import UnauthorizedError
from keeper.execution.features.claim_execution.command import ClaimExecution
from keeper.execution.features.claim_execution.decider import decide
from keeper.infrastructure.kernel import Kernel
from keeper.infrastructure.logging import get_logger
from keeper.infrastructure.ports import Deny
from keeper.infrastructure.slices.envelope import to_new_event
from keeper.shared.reserved_ids import NIL_SENTINEL_ID

_COMMAND_NAME = "ClaimExecution"

_log = get_logger(__name__)


class Handler(Protocol):
    """The bare handler, before the wrapping the wire module applies."""

    async def __call__(
        self,
        command: ClaimExecution,
        *,
        principal_id: UUID,
        correlation_id: UUID,
        causation_id: UUID | None = None,
        surface_id: UUID = NIL_SENTINEL_ID,
    ) -> None: ...


def bind(deps: Kernel) -> Handler:
    """Build the handler, closed over the process-wide dependencies."""

    async def handler(
        command: ClaimExecution,
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
                "claim_execution.denied",
                command_name=_COMMAND_NAME,
                execution_id=str(command.execution_id),
                principal_id=str(principal_id),
                correlation_id=str(correlation_id),
                reason=decision.reason,
            )
            raise UnauthorizedError(decision.reason)

        state, version = await load_execution_with_version(deps.event_store, command.execution_id)
        now = command.occurred_at if command.occurred_at is not None else deps.clock.now()
        events = decide(state, command, now=now)

        await deps.event_store.append(
            EXECUTION_STREAM_TYPE,
            command.execution_id,
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
            "claim_execution.success",
            command_name=_COMMAND_NAME,
            execution_id=str(command.execution_id),
            principal_id=str(principal_id),
            correlation_id=str(correlation_id),
        )

    return handler


__all__ = ["Handler", "bind"]
