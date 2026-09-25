"""Answer the question: authorize, load, return.

No decider, no append, no clock. A read produces no events, so there is
nothing for a pure decision function to decide and nothing to make
reproducible on replay.

Authorization still happens. A proposal says which agent advised what,
and whether anybody acted on it, which is more than a deployment
necessarily wants every caller to learn.

`ProposalNotFoundError` rather than a `None` return. The aggregate's
`load_proposal` returns None and leaves the meaning to its caller, which
is this handler: both surfaces want a refusal, and raising the same
error shape the sibling contexts raise gets it mapped in one place
instead of two.
"""

from typing import Protocol
from uuid import UUID

from keeper.counsel.aggregates.proposal import (
    Proposal,
    ProposalNotFoundError,
    load_proposal,
)
from keeper.counsel.errors import UnauthorizedError
from keeper.counsel.features.get_proposal.query import GetProposal
from keeper.infrastructure.kernel import Kernel
from keeper.infrastructure.logging import get_logger
from keeper.infrastructure.ports import Deny
from keeper.shared.reserved_ids import NIL_SENTINEL_ID

_COMMAND_NAME = "GetProposal"

_log = get_logger(__name__)


class Handler(Protocol):
    """The bare handler, before the wrapping the wire module applies."""

    async def __call__(
        self,
        query: GetProposal,
        *,
        principal_id: UUID,
        correlation_id: UUID,
        causation_id: UUID | None = None,
        surface_id: UUID = NIL_SENTINEL_ID,
    ) -> Proposal: ...


def bind(deps: Kernel) -> Handler:
    """Build the handler, closed over the process-wide dependencies."""

    async def handler(
        query: GetProposal,
        *,
        principal_id: UUID,
        correlation_id: UUID,
        causation_id: UUID | None = None,
        surface_id: UUID = NIL_SENTINEL_ID,
    ) -> Proposal:
        _ = causation_id
        decision = await deps.authz.authorize(
            principal_id=principal_id,
            command_name=_COMMAND_NAME,
            surface_id=surface_id,
        )
        if isinstance(decision, Deny):
            _log.info(
                "get_proposal.denied",
                command_name=_COMMAND_NAME,
                proposal_id=str(query.proposal_id),
                principal_id=str(principal_id),
                correlation_id=str(correlation_id),
                reason=decision.reason,
            )
            raise UnauthorizedError(decision.reason)

        proposal = await load_proposal(deps.event_store, query.proposal_id)
        if proposal is None:
            raise ProposalNotFoundError(query.proposal_id)
        return proposal

    return handler


__all__ = ["Handler", "bind"]
