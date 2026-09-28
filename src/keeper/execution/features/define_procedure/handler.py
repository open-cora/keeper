"""Run the definition: authorize, load the operations, decide, append.

Create-style shape. A freshly minted id provably has no history, so this
handler skips the load-and-fold that an editing handler starts with and
hands `state=None` straight to the decider.

The operations the acquisitions cite are read and not touched, so one store is
written and there is no ordering to get right. Each distinct operation is read
once: a procedure acquiring the same operation at twenty sample positions
should not replay that stream twenty times.

A procedure citing an operation that does not exist is refused here rather than
in the decider, because discovering the absence needs the store and the
decider has none. That is the split docs/reference/patterns.md draws
between a 404 and a refusal, and every slice in this tree that reads a
sibling draws it the same way.
"""

from typing import Protocol
from uuid import UUID

from keeper.execution.aggregates.operation import Operation, OperationNotFoundError, load_operation
from keeper.execution.aggregates.procedure import (
    PROCEDURE_STREAM_TYPE,
    AcquireStep,
    to_payload,
)
from keeper.execution.features.define_procedure.command import DefineProcedure
from keeper.execution.features.define_procedure.context import DefineProcedureContext
from keeper.execution.features.define_procedure.decider import decide
from keeper.infrastructure.kernel import Kernel
from keeper.infrastructure.logging import get_logger
from keeper.infrastructure.ports import Deny
from keeper.infrastructure.slices.envelope import to_new_event
from keeper.shared.reserved_ids import NIL_SENTINEL_ID
from keeper.shared.unauthorized import UnauthorizedError

_COMMAND_NAME = "DefineProcedure"

_log = get_logger(__name__)


class Handler(Protocol):
    """The bare handler, before the wrapping the wire module applies."""

    async def __call__(
        self,
        command: DefineProcedure,
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
        command: DefineProcedure,
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
        command: DefineProcedure,
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
                "define_procedure.denied",
                command_name=_COMMAND_NAME,
                principal_id=str(principal_id),
                correlation_id=str(correlation_id),
                reason=decision.reason,
            )
            raise UnauthorizedError(decision.reason)

        operations: dict[UUID, Operation] = {}
        for step in command.steps:
            if not isinstance(step, AcquireStep) or step.operation_id in operations:
                continue
            operation = await load_operation(deps.event_store, step.operation_id)
            if operation is None:
                raise OperationNotFoundError(step.operation_id)
            operations[step.operation_id] = operation

        new_id = deps.id_generator.new_id()
        now = deps.clock.now()
        events = decide(
            None,
            command,
            context=DefineProcedureContext(operations=operations),
            now=now,
            new_id=new_id,
            step_ids=[deps.id_generator.new_id() for _ in command.steps],
        )

        await deps.event_store.append(
            PROCEDURE_STREAM_TYPE,
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
            "define_procedure.success",
            command_name=_COMMAND_NAME,
            procedure_id=str(new_id),
            principal_id=str(principal_id),
            correlation_id=str(correlation_id),
        )
        return new_id

    return handler


__all__ = ["Handler", "IdempotentHandler", "bind"]
