"""Answer the question: authorize, load, return.

No decider, no append, no clock. A read produces no events, so there is
nothing for a pure decision function to decide and nothing to make
reproducible on replay.

Authorization still happens. A dataset record says that a particular run
produced data and says where that data is kept, which is two things a
deployment should get to decide who may learn. Reading one is close to
the strongest thing this context can tell somebody.

`DatasetNotFoundError` rather than a `None` return. The aggregate's
`load_dataset` returns None and leaves the meaning to its caller, which
is this handler: both surfaces want a refusal, and raising the same error
shape the sibling contexts raise gets it mapped in one place instead of
two.
"""

from typing import Protocol
from uuid import UUID

from keeper.custody.aggregates.dataset import (
    Dataset,
    DatasetNotFoundError,
    load_dataset,
)
from keeper.custody.errors import UnauthorizedError
from keeper.custody.features.get_dataset.query import GetDataset
from keeper.infrastructure.kernel import Kernel
from keeper.infrastructure.logging import get_logger
from keeper.infrastructure.ports import Deny
from keeper.shared.reserved_ids import NIL_SENTINEL_ID

_COMMAND_NAME = "GetDataset"

_log = get_logger(__name__)


class Handler(Protocol):
    """The bare handler, before the wrapping the wire module applies."""

    async def __call__(
        self,
        query: GetDataset,
        *,
        principal_id: UUID,
        correlation_id: UUID,
        causation_id: UUID | None = None,
        surface_id: UUID = NIL_SENTINEL_ID,
    ) -> Dataset: ...


def bind(deps: Kernel) -> Handler:
    """Build the handler, closed over the process-wide dependencies."""

    async def handler(
        query: GetDataset,
        *,
        principal_id: UUID,
        correlation_id: UUID,
        causation_id: UUID | None = None,
        surface_id: UUID = NIL_SENTINEL_ID,
    ) -> Dataset:
        _ = causation_id
        decision = await deps.authz.authorize(
            principal_id=principal_id,
            command_name=_COMMAND_NAME,
            surface_id=surface_id,
        )
        if isinstance(decision, Deny):
            _log.info(
                "get_dataset.denied",
                command_name=_COMMAND_NAME,
                dataset_id=str(query.dataset_id),
                principal_id=str(principal_id),
                correlation_id=str(correlation_id),
                reason=decision.reason,
            )
            raise UnauthorizedError(decision.reason)

        dataset = await load_dataset(deps.event_store, query.dataset_id)
        if dataset is None:
            raise DatasetNotFoundError(query.dataset_id)
        return dataset

    return handler


__all__ = ["Handler", "bind"]
