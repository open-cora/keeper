"""Answer the question: authorize, clamp, read the summaries.

No decider, no append, no clock, the same as the read beside it. What is
different is where the answer comes from: `get_dataset` folds a stream,
and this reads a table a projection maintains, through a port so that the
environment with no database can answer too.

Authorization is the same gate the single read uses, and the reason is
stronger here. One dataset record says where one run's data is kept; a
page of them says where a deployment keeps everything, which is a map
rather than an address.

The limit is clamped rather than refused. A caller asking for two hundred
rows has not done anything wrong, they have asked for more than this
server hands out at once, and the honest answer is a hundred rows and a
cursor rather than a 400 and no data.
"""

from typing import Protocol
from uuid import UUID

from keeper.custody.aggregates.dataset.summary import (
    DatasetSummaryLookup,
    DatasetSummaryPage,
)
from keeper.custody.errors import UnauthorizedError
from keeper.custody.features.list_datasets.query import MAX_PAGE_SIZE, ListDatasets
from keeper.infrastructure.kernel import Kernel
from keeper.infrastructure.logging import get_logger
from keeper.infrastructure.ports import Deny
from keeper.shared.reserved_ids import NIL_SENTINEL_ID

_COMMAND_NAME = "ListDatasets"

_log = get_logger(__name__)


class Handler(Protocol):
    """The bare handler, before the wrapping the wire module applies."""

    async def __call__(
        self,
        query: ListDatasets,
        *,
        principal_id: UUID,
        correlation_id: UUID,
        causation_id: UUID | None = None,
        surface_id: UUID = NIL_SENTINEL_ID,
    ) -> DatasetSummaryPage: ...


def bind(deps: Kernel, summaries: DatasetSummaryLookup) -> Handler:
    """Build the handler, closed over the dependencies and the read port.

    Two arguments rather than one. Every other slice in this context takes
    the kernel alone, because everything it needs is on the kernel; the
    read port is not, and cannot be, because the kernel is declared in
    infrastructure and a dataset summary is Custody's own idea. The wire
    module picks which implementation this gets.
    """

    async def handler(
        query: ListDatasets,
        *,
        principal_id: UUID,
        correlation_id: UUID,
        causation_id: UUID | None = None,
        surface_id: UUID = NIL_SENTINEL_ID,
    ) -> DatasetSummaryPage:
        _ = causation_id
        decision = await deps.authz.authorize(
            principal_id=principal_id,
            command_name=_COMMAND_NAME,
            surface_id=surface_id,
        )
        if isinstance(decision, Deny):
            _log.info(
                "list_datasets.denied",
                command_name=_COMMAND_NAME,
                principal_id=str(principal_id),
                correlation_id=str(correlation_id),
                reason=decision.reason,
            )
            raise UnauthorizedError(decision.reason)

        return await summaries.list_datasets(
            step_id=query.step_id,
            limit=min(query.limit, MAX_PAGE_SIZE),
            cursor=query.cursor,
        )

    return handler


__all__ = ["Handler", "bind"]
