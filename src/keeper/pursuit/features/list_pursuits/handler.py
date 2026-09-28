"""Read a page of pursuits: authorize, then ask the port.

The port rather than the pool, because this has to answer with no database
at all. Which implementation it gets is decided in `wire.py`.
"""

from typing import Protocol
from uuid import UUID

from keeper.infrastructure.kernel import Kernel
from keeper.infrastructure.logging import get_logger
from keeper.infrastructure.ports import Deny
from keeper.pursuit.aggregates.pursuit.summary import PursuitSummaryLookup, PursuitSummaryPage
from keeper.pursuit.features.list_pursuits.query import MAX_PAGE_SIZE, ListPursuits
from keeper.shared.reserved_ids import NIL_SENTINEL_ID
from keeper.shared.unauthorized import UnauthorizedError

_COMMAND_NAME = "ListPursuits"

_log = get_logger(__name__)


class Handler(Protocol):
    """The bare handler, before the wrapping the wire module applies."""

    async def __call__(
        self,
        query: ListPursuits,
        *,
        principal_id: UUID,
        correlation_id: UUID,
        causation_id: UUID | None = None,
        surface_id: UUID = NIL_SENTINEL_ID,
    ) -> PursuitSummaryPage: ...


def bind(deps: Kernel, summaries: PursuitSummaryLookup) -> Handler:
    """Build the handler, closed over the dependencies and the read port."""

    async def handler(
        query: ListPursuits,
        *,
        principal_id: UUID,
        correlation_id: UUID,
        causation_id: UUID | None = None,
        surface_id: UUID = NIL_SENTINEL_ID,
    ) -> PursuitSummaryPage:
        _ = causation_id
        decision = await deps.authz.authorize(
            principal_id=principal_id,
            command_name=_COMMAND_NAME,
            surface_id=surface_id,
        )
        if isinstance(decision, Deny):
            _log.info(
                "list_pursuits.denied",
                command_name=_COMMAND_NAME,
                principal_id=str(principal_id),
                correlation_id=str(correlation_id),
                reason=decision.reason,
            )
            raise UnauthorizedError(decision.reason)

        return await summaries.list_pursuits(
            status=query.status,
            beamline=query.beamline,
            limit=min(query.limit, MAX_PAGE_SIZE),
            cursor=query.cursor,
        )

    return handler


__all__ = ["Handler", "bind"]
