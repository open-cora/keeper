"""Answer the question: authorize, load, return.

No decider, no append, no clock. A read produces no events, so there is
nothing for a pure decision function to decide and nothing to make
reproducible on replay.

Authorization still happens. An operation says what this system can be asked to
run and what each request has to look like, so a caller who can read one
learns the shape of a command they may not be permitted to send.

`OperationNotFoundError` rather than a `None` return. The aggregate's
`load_operation` returns None and leaves the meaning to its caller, which is
this handler: both surfaces want a refusal, and raising the same error
the writing slice raises gets it mapped in one place instead of two.
"""

from typing import Protocol
from uuid import UUID

from keeper.execution.aggregates.operation import Operation, OperationNotFoundError, load_operation
from keeper.execution.features.get_operation.query import GetOperation
from keeper.infrastructure.kernel import Kernel
from keeper.infrastructure.logging import get_logger
from keeper.infrastructure.ports import Deny
from keeper.shared.reserved_ids import NIL_SENTINEL_ID
from keeper.shared.unauthorized import UnauthorizedError

_COMMAND_NAME = "GetOperation"

_log = get_logger(__name__)


class Handler(Protocol):
    """The bare handler, before the wrapping the wire module applies."""

    async def __call__(
        self,
        query: GetOperation,
        *,
        principal_id: UUID,
        correlation_id: UUID,
        causation_id: UUID | None = None,
        surface_id: UUID = NIL_SENTINEL_ID,
    ) -> Operation: ...


def bind(deps: Kernel) -> Handler:
    """Build the handler, closed over the process-wide dependencies."""

    async def handler(
        query: GetOperation,
        *,
        principal_id: UUID,
        correlation_id: UUID,
        causation_id: UUID | None = None,
        surface_id: UUID = NIL_SENTINEL_ID,
    ) -> Operation:
        _ = causation_id
        decision = await deps.authz.authorize(
            principal_id=principal_id,
            command_name=_COMMAND_NAME,
            surface_id=surface_id,
        )
        if isinstance(decision, Deny):
            _log.info(
                "get_operation.denied",
                command_name=_COMMAND_NAME,
                operation_id=str(query.operation_id),
                principal_id=str(principal_id),
                correlation_id=str(correlation_id),
                reason=decision.reason,
            )
            raise UnauthorizedError(decision.reason)

        operation = await load_operation(deps.event_store, query.operation_id)
        if operation is None:
            raise OperationNotFoundError(query.operation_id)
        return operation

    return handler


__all__ = ["Handler", "bind"]
