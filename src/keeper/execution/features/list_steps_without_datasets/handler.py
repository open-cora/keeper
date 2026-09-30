"""Answer the listing: authorize, then ask the read port.

No decider and no event store. This slice never folds a stream: the
question is which steps to name, and an event log answers that only if
something kept a summary as the events arrived.

## Why the gate is its own command

`ListStepsWithoutDatasets` rather than reusing the one that reads
executions. A page of executions says what a facility is doing; a page
of gaps says where its record of itself is incomplete, which is the
question somebody asks before an audit and not the question a conductor
asks to find work. Granting one should not grant the other, and a
shared gate would make that impossible to express.

The limit is clamped here rather than trusted, because both surfaces
can send one and only this side pays for it.
"""

from typing import Protocol
from uuid import UUID

from keeper.execution.aggregates.execution import StepSummaryLookup, StepSummaryPage
from keeper.execution.features.list_steps_without_datasets.query import (
    MAX_PAGE_SIZE,
    ListStepsWithoutDatasets,
)
from keeper.infrastructure.kernel import Kernel
from keeper.infrastructure.logging import get_logger
from keeper.infrastructure.ports import Deny
from keeper.shared.reserved_ids import NIL_SENTINEL_ID
from keeper.shared.unauthorized import UnauthorizedError

_COMMAND_NAME = "ListStepsWithoutDatasets"

_log = get_logger(__name__)


class Handler(Protocol):
    """The bare handler, before the wrapping the wire module applies."""

    async def __call__(
        self,
        query: ListStepsWithoutDatasets,
        *,
        principal_id: UUID,
        correlation_id: UUID,
        causation_id: UUID | None = None,
        surface_id: UUID = NIL_SENTINEL_ID,
    ) -> StepSummaryPage: ...


def bind(deps: Kernel, summaries: StepSummaryLookup) -> Handler:
    """Build the handler, closed over the dependencies and the read port.

    Two arguments rather than one, for the reason every listing here
    takes two: the read port is not on the kernel and cannot be,
    because the kernel is declared in infrastructure and a step summary
    is Execution's own idea. The wire module picks which implementation
    this gets.
    """

    async def handler(
        query: ListStepsWithoutDatasets,
        *,
        principal_id: UUID,
        correlation_id: UUID,
        causation_id: UUID | None = None,
        surface_id: UUID = NIL_SENTINEL_ID,
    ) -> StepSummaryPage:
        _ = causation_id
        decision = await deps.authz.authorize(
            principal_id=principal_id,
            command_name=_COMMAND_NAME,
            surface_id=surface_id,
        )
        if isinstance(decision, Deny):
            _log.info(
                "list_steps_without_datasets.denied",
                command_name=_COMMAND_NAME,
                principal_id=str(principal_id),
                correlation_id=str(correlation_id),
                reason=decision.reason,
            )
            raise UnauthorizedError(decision.reason)

        return await summaries.list_steps_without_datasets(
            beamline=query.beamline,
            limit=min(query.limit, MAX_PAGE_SIZE),
            cursor=query.cursor,
        )

    return handler


__all__ = ["Handler", "bind"]
