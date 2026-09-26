"""Answer the question: authorize, load, return.

No decider, no append, no clock. A read produces no events, so there is
nothing for a pure decision function to decide and nothing to make
reproducible on replay.

Authorization still happens. An inquiry says what somebody wanted to know
and what a thinker told them, which is more than a deployment necessarily
wants every caller to learn.

`InquiryNotFoundError` rather than a `None` return. The aggregate's
`load_inquiry` returns None and leaves the meaning to its caller, which is
this handler: both surfaces want a refusal, and raising the same error
shape the sibling slices raise gets it mapped in one place instead of two.
"""

from typing import Protocol
from uuid import UUID

from keeper.counsel.aggregates.inquiry import (
    Inquiry,
    InquiryNotFoundError,
    load_inquiry,
)
from keeper.counsel.errors import UnauthorizedError
from keeper.counsel.features.get_inquiry.query import GetInquiry
from keeper.infrastructure.kernel import Kernel
from keeper.infrastructure.logging import get_logger
from keeper.infrastructure.ports import Deny
from keeper.shared.reserved_ids import NIL_SENTINEL_ID

_COMMAND_NAME = "GetInquiry"

_log = get_logger(__name__)


class Handler(Protocol):
    """The bare handler, before the wrapping the wire module applies."""

    async def __call__(
        self,
        query: GetInquiry,
        *,
        principal_id: UUID,
        correlation_id: UUID,
        causation_id: UUID | None = None,
        surface_id: UUID = NIL_SENTINEL_ID,
    ) -> Inquiry: ...


def bind(deps: Kernel) -> Handler:
    """Build the handler, closed over the process-wide dependencies."""

    async def handler(
        query: GetInquiry,
        *,
        principal_id: UUID,
        correlation_id: UUID,
        causation_id: UUID | None = None,
        surface_id: UUID = NIL_SENTINEL_ID,
    ) -> Inquiry:
        _ = causation_id
        decision = await deps.authz.authorize(
            principal_id=principal_id,
            command_name=_COMMAND_NAME,
            surface_id=surface_id,
        )
        if isinstance(decision, Deny):
            _log.info(
                "get_inquiry.denied",
                command_name=_COMMAND_NAME,
                inquiry_id=str(query.inquiry_id),
                principal_id=str(principal_id),
                correlation_id=str(correlation_id),
                reason=decision.reason,
            )
            raise UnauthorizedError(decision.reason)

        inquiry = await load_inquiry(deps.event_store, query.inquiry_id)
        if inquiry is None:
            raise InquiryNotFoundError(query.inquiry_id)
        return inquiry

    return handler


__all__ = ["Handler", "bind"]
