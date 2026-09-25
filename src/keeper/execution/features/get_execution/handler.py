"""Answer the question: authorize, load, return.

No decider, no append, no clock. A read produces no events, so there is
nothing for a pure decision function to decide.

Authorization still happens. An execution record says what was driven and how
each step of it went, which is a description of activity rather than of
configuration, so who may read one is a question a deployment should get
to answer.

`ExecutionNotFoundError` rather than a `None` return. The aggregate's
`load_execution` returns None and leaves the meaning to its caller, which is
this handler: both surfaces want a refusal, and raising the same error
the writing slices raise gets it mapped in one place instead of two.
"""

from typing import Protocol
from uuid import UUID

from keeper.execution.aggregates.execution import Execution, ExecutionNotFoundError, load_execution
from keeper.execution.errors import UnauthorizedError
from keeper.execution.features.get_execution.query import GetExecution
from keeper.infrastructure.kernel import Kernel
from keeper.infrastructure.logging import get_logger
from keeper.infrastructure.ports import Deny
from keeper.shared.reserved_ids import NIL_SENTINEL_ID

_COMMAND_NAME = "GetExecution"

_log = get_logger(__name__)


class Handler(Protocol):
    """The bare handler, before the wrapping the wire module applies."""

    async def __call__(
        self,
        query: GetExecution,
        *,
        principal_id: UUID,
        correlation_id: UUID,
        causation_id: UUID | None = None,
        surface_id: UUID = NIL_SENTINEL_ID,
    ) -> Execution: ...


def bind(deps: Kernel) -> Handler:
    """Build the handler, closed over the process-wide dependencies."""

    async def handler(
        query: GetExecution,
        *,
        principal_id: UUID,
        correlation_id: UUID,
        causation_id: UUID | None = None,
        surface_id: UUID = NIL_SENTINEL_ID,
    ) -> Execution:
        _ = causation_id
        decision = await deps.authz.authorize(
            principal_id=principal_id,
            command_name=_COMMAND_NAME,
            surface_id=surface_id,
        )
        if isinstance(decision, Deny):
            _log.info(
                "get_execution.denied",
                command_name=_COMMAND_NAME,
                execution_id=str(query.execution_id),
                principal_id=str(principal_id),
                correlation_id=str(correlation_id),
                reason=decision.reason,
            )
            raise UnauthorizedError(decision.reason)

        execution = await load_execution(deps.event_store, query.execution_id)
        if execution is None:
            raise ExecutionNotFoundError(query.execution_id)
        return execution

    return handler


__all__ = ["Handler", "bind"]
