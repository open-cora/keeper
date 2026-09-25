"""Answer the listing: authorize, then ask the read port.

No decider and no event store. This slice never folds a stream: the
question is which execution to name, and an event log answers that only if
something kept a summary as the events arrived.

The limit is clamped here rather than trusted, because both surfaces can
send one and only this side pays for it.
"""

from typing import Protocol
from uuid import UUID

from keeper.execution.aggregates.execution import ExecutionSummaryLookup, ExecutionSummaryPage
from keeper.execution.errors import UnauthorizedError
from keeper.execution.features.list_executions.query import MAX_PAGE_SIZE, ListExecutions
from keeper.infrastructure.kernel import Kernel
from keeper.infrastructure.logging import get_logger
from keeper.infrastructure.ports import Deny
from keeper.shared.reserved_ids import NIL_SENTINEL_ID

_COMMAND_NAME = "ListExecutions"

_log = get_logger(__name__)


class Handler(Protocol):
    """The bare handler, before the wrapping the wire module applies."""

    async def __call__(
        self,
        query: ListExecutions,
        *,
        principal_id: UUID,
        correlation_id: UUID,
        causation_id: UUID | None = None,
        surface_id: UUID = NIL_SENTINEL_ID,
    ) -> ExecutionSummaryPage: ...


def bind(deps: Kernel, summaries: ExecutionSummaryLookup) -> Handler:
    """Build the handler, closed over the dependencies and the read port.

    Two arguments rather than one, for the reason `list_plans` takes two:
    the read port is not on the kernel and cannot be, because the kernel
    is declared in infrastructure and an execution summary is Execution's
    own idea. The wire module picks which implementation this gets.
    """

    async def handler(
        query: ListExecutions,
        *,
        principal_id: UUID,
        correlation_id: UUID,
        causation_id: UUID | None = None,
        surface_id: UUID = NIL_SENTINEL_ID,
    ) -> ExecutionSummaryPage:
        _ = causation_id
        decision = await deps.authz.authorize(
            principal_id=principal_id,
            command_name=_COMMAND_NAME,
            surface_id=surface_id,
        )
        if isinstance(decision, Deny):
            _log.info(
                "list_executions.denied",
                command_name=_COMMAND_NAME,
                principal_id=str(principal_id),
                correlation_id=str(correlation_id),
                reason=decision.reason,
            )
            raise UnauthorizedError(decision.reason)

        return await summaries.list_executions(
            procedure_id=query.procedure_id,
            beamline=query.beamline,
            status=query.status,
            limit=min(query.limit, MAX_PAGE_SIZE),
            cursor=query.cursor,
        )

    return handler


__all__ = ["Handler", "bind"]
