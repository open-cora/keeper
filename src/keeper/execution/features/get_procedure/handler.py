"""Answer the question: authorize, load, return.

No decider, no append, no clock. A read produces no events, so there is
nothing for a pure decision function to decide and nothing to make
reproducible on replay.

Authorization still happens. A procedure says what this system composed
and which devices each step will hold, which is a picture of what a
beamline is about to do, and a deployment should get to decide who sees
it.

`ProcedureNotFoundError` rather than a `None` return. The aggregate's
`load_procedure` returns None and leaves the meaning to its caller,
which is this handler: both surfaces want a refusal, and raising the
same error the writing slice raises gets it mapped in one place instead
of two.
"""

from typing import Protocol
from uuid import UUID

from keeper.execution.aggregates.procedure import (
    Procedure,
    ProcedureNotFoundError,
    load_procedure,
)
from keeper.execution.errors import UnauthorizedError
from keeper.execution.features.get_procedure.query import GetProcedure
from keeper.infrastructure.kernel import Kernel
from keeper.infrastructure.logging import get_logger
from keeper.infrastructure.ports import Deny
from keeper.shared.reserved_ids import NIL_SENTINEL_ID

_COMMAND_NAME = "GetProcedure"

_log = get_logger(__name__)


class Handler(Protocol):
    """The bare handler, before the wrapping the wire module applies."""

    async def __call__(
        self,
        query: GetProcedure,
        *,
        principal_id: UUID,
        correlation_id: UUID,
        causation_id: UUID | None = None,
        surface_id: UUID = NIL_SENTINEL_ID,
    ) -> Procedure: ...


def bind(deps: Kernel) -> Handler:
    """Build the handler, closed over the process-wide dependencies."""

    async def handler(
        query: GetProcedure,
        *,
        principal_id: UUID,
        correlation_id: UUID,
        causation_id: UUID | None = None,
        surface_id: UUID = NIL_SENTINEL_ID,
    ) -> Procedure:
        _ = causation_id
        decision = await deps.authz.authorize(
            principal_id=principal_id,
            command_name=_COMMAND_NAME,
            surface_id=surface_id,
        )
        if isinstance(decision, Deny):
            _log.info(
                "get_procedure.denied",
                command_name=_COMMAND_NAME,
                procedure_id=str(query.procedure_id),
                principal_id=str(principal_id),
                correlation_id=str(correlation_id),
                reason=decision.reason,
            )
            raise UnauthorizedError(decision.reason)

        procedure = await load_procedure(deps.event_store, query.procedure_id)
        if procedure is None:
            raise ProcedureNotFoundError(query.procedure_id)
        return procedure

    return handler


__all__ = ["Handler", "bind"]
