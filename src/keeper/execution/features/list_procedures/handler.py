"""Answer the question: authorize, clamp, read the summaries.

The plan list's sibling and the same three steps. No decider, no append,
no clock, and the answer comes from a port rather than from a fold, so
the environment with no database can answer too.

Authorization is the same gate the other reads use. What procedures exist
is a description of what this system has been composed to do, which is a
question a deployment should get to answer for itself.
"""

from typing import Protocol
from uuid import UUID

from keeper.execution.aggregates.procedure.summary import (
    ProcedureSummaryLookup,
    ProcedureSummaryPage,
)
from keeper.execution.errors import UnauthorizedError
from keeper.execution.features.list_procedures.query import MAX_PAGE_SIZE, ListProcedures
from keeper.infrastructure.kernel import Kernel
from keeper.infrastructure.logging import get_logger
from keeper.infrastructure.ports import Deny
from keeper.shared.reserved_ids import NIL_SENTINEL_ID

_COMMAND_NAME = "ListProcedures"

_log = get_logger(__name__)


class Handler(Protocol):
    """The bare handler, before the wrapping the wire module applies."""

    async def __call__(
        self,
        query: ListProcedures,
        *,
        principal_id: UUID,
        correlation_id: UUID,
        causation_id: UUID | None = None,
        surface_id: UUID = NIL_SENTINEL_ID,
    ) -> ProcedureSummaryPage: ...


def bind(deps: Kernel, summaries: ProcedureSummaryLookup) -> Handler:
    """Build the handler, closed over the dependencies and the read port.

    Two arguments, like the plan list and for the same reason: the read
    port is not on the kernel and cannot be, because the kernel is
    declared in infrastructure and a procedure summary is Execution's own
    idea.
    """

    async def handler(
        query: ListProcedures,
        *,
        principal_id: UUID,
        correlation_id: UUID,
        causation_id: UUID | None = None,
        surface_id: UUID = NIL_SENTINEL_ID,
    ) -> ProcedureSummaryPage:
        _ = causation_id
        decision = await deps.authz.authorize(
            principal_id=principal_id,
            command_name=_COMMAND_NAME,
            surface_id=surface_id,
        )
        if isinstance(decision, Deny):
            _log.info(
                "list_procedures.denied",
                command_name=_COMMAND_NAME,
                principal_id=str(principal_id),
                correlation_id=str(correlation_id),
                reason=decision.reason,
            )
            raise UnauthorizedError(decision.reason)

        return await summaries.list_procedures(
            name=query.name,
            limit=min(query.limit, MAX_PAGE_SIZE),
            cursor=query.cursor,
        )

    return handler


__all__ = ["Handler", "bind"]
