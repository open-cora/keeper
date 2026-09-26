"""Answer the question: authorize, read the summaries, return.

No decider and no append. A read produces no events, so there is nothing
for a pure decision function to decide.

Unlike `get_inquiry`, this one cannot fold: the question names no stream.
It goes through a read port instead, and which implementation it gets is
the wire module's choice, made on whether the deployment has a pool.
"""

from typing import Protocol
from uuid import UUID

from keeper.counsel.aggregates.inquiry import InquirySummaryLookup, InquirySummaryPage
from keeper.counsel.errors import UnauthorizedError
from keeper.counsel.features.list_inquiries.query import MAX_PAGE_SIZE, ListInquiries
from keeper.infrastructure.kernel import Kernel
from keeper.infrastructure.logging import get_logger
from keeper.infrastructure.ports import Deny
from keeper.shared.reserved_ids import NIL_SENTINEL_ID

_COMMAND_NAME = "ListInquiries"

_log = get_logger(__name__)


class Handler(Protocol):
    """The bare handler, before the wrapping the wire module applies."""

    async def __call__(
        self,
        query: ListInquiries,
        *,
        principal_id: UUID,
        correlation_id: UUID,
        causation_id: UUID | None = None,
        surface_id: UUID = NIL_SENTINEL_ID,
    ) -> InquirySummaryPage: ...


def bind(deps: Kernel, summaries: InquirySummaryLookup) -> Handler:
    """Build the handler, closed over the dependencies and the read port.

    Two arguments rather than one, which is `list_proposals`' shape and for
    its reason: the read port is not on the kernel and cannot be, because
    the kernel is declared in infrastructure and an inquiry summary is
    Counsel's own idea.
    """

    async def handler(
        query: ListInquiries,
        *,
        principal_id: UUID,
        correlation_id: UUID,
        causation_id: UUID | None = None,
        surface_id: UUID = NIL_SENTINEL_ID,
    ) -> InquirySummaryPage:
        _ = causation_id
        decision = await deps.authz.authorize(
            principal_id=principal_id,
            command_name=_COMMAND_NAME,
            surface_id=surface_id,
        )
        if isinstance(decision, Deny):
            _log.info(
                "list_inquiries.denied",
                command_name=_COMMAND_NAME,
                principal_id=str(principal_id),
                correlation_id=str(correlation_id),
                reason=decision.reason,
            )
            raise UnauthorizedError(decision.reason)

        return await summaries.list_inquiries(
            status=query.status,
            limit=min(query.limit, MAX_PAGE_SIZE),
            cursor=query.cursor,
        )

    return handler


__all__ = ["Handler", "bind"]
