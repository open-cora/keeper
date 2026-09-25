"""Dispatch the execution: authorize, read the procedure, decide, append.

Create-style on its own stream, so there is no load-and-fold of an execution
and `state=None` goes straight to the decider.

A context module, like `define_procedure` next door, because the decision
copies a procedure's name and steps and the procedure is a different
stream. The procedure is read and not touched, so one store is written
and there is no ordering to get right.

A dispatch naming a procedure that does not exist is refused here rather
than in the decider, because discovering the absence needs the store and
the decider has none.
"""

from typing import Protocol
from uuid import UUID

from keeper.execution.aggregates.execution import EXECUTION_STREAM_TYPE, to_payload
from keeper.execution.aggregates.procedure import ProcedureNotFoundError, load_procedure
from keeper.execution.errors import UnauthorizedError
from keeper.execution.features.dispatch_execution.command import DispatchExecution
from keeper.execution.features.dispatch_execution.context import DispatchExecutionContext
from keeper.execution.features.dispatch_execution.decider import decide
from keeper.infrastructure.kernel import Kernel
from keeper.infrastructure.logging import get_logger
from keeper.infrastructure.ports import Deny
from keeper.infrastructure.slices.envelope import to_new_event
from keeper.shared.reserved_ids import NIL_SENTINEL_ID

_COMMAND_NAME = "DispatchExecution"

_log = get_logger(__name__)


class Handler(Protocol):
    """The bare handler, before the wrapping the wire module applies."""

    async def __call__(
        self,
        command: DispatchExecution,
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
        command: DispatchExecution,
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
        command: DispatchExecution,
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
                "dispatch_execution.denied",
                command_name=_COMMAND_NAME,
                principal_id=str(principal_id),
                correlation_id=str(correlation_id),
                reason=decision.reason,
            )
            raise UnauthorizedError(decision.reason)

        procedure = await load_procedure(deps.event_store, command.procedure_id)
        if procedure is None:
            raise ProcedureNotFoundError(command.procedure_id)

        new_id = deps.id_generator.new_id()
        events = decide(
            None,
            command,
            context=DispatchExecutionContext(procedure=procedure),
            now=deps.clock.now(),
            new_id=new_id,
            step_ids=[deps.id_generator.new_id() for _ in procedure.steps],
        )

        await deps.event_store.append(
            EXECUTION_STREAM_TYPE,
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
            "dispatch_execution.success",
            command_name=_COMMAND_NAME,
            execution_id=str(new_id),
            procedure_id=str(command.procedure_id),
            step_count=len(procedure.steps),
            principal_id=str(principal_id),
            correlation_id=str(correlation_id),
        )
        return new_id

    return handler


__all__ = ["Handler", "IdempotentHandler", "bind"]
