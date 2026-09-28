"""Record the answer: authorize, load, check the proposal, decide, append.

Update-style, so this command names a stream that already has a row. The
handler folds that history before deciding and passes the version it read
back as `expected_version`.

That version is the whole of the concurrency story. Two thinkers answering
one question at once both fold the same state and both decide to append at
the same version; the store lets one through and raises `ConcurrencyError`
at the other, which surfaces as a 409. Without it the second append would
land a second conclusion against an inquiry that already had one, which the
decider exists to refuse.

**The proposal is loaded only when one is named**, and only to establish
that it exists. This is the one citation in this context that points
sideways at its own neighbour rather than across at Execution, so the check
costs a load and no door. What it buys is that a `Propose` answer cannot
cite a proposal nobody made, which would leave the join this context exists
to hold pointing at nothing.

Nothing compares the proposal's operation against anything here. The inquiry
names an execution rather than an operation, so there is no second opinion to
check it against, and the thinker that wrote the proposal is the one
reporting it.

No idempotency wrapper. A replayed answer is already refused by the domain,
so the wrapper would be buying a nicer status code for a retry rather than
preventing a duplicate.
"""

from typing import Protocol
from uuid import UUID

from keeper.counsel.aggregates.inquiry import (
    INQUIRY_STREAM_TYPE,
    load_inquiry_with_version,
    to_payload,
)
from keeper.counsel.aggregates.proposal import ProposalNotFoundError, load_proposal
from keeper.counsel.features.answer_inquiry.command import AnswerInquiry
from keeper.counsel.features.answer_inquiry.decider import decide
from keeper.infrastructure.kernel import Kernel
from keeper.infrastructure.logging import get_logger
from keeper.infrastructure.ports import Deny
from keeper.infrastructure.slices.envelope import to_new_event
from keeper.shared.reserved_ids import NIL_SENTINEL_ID
from keeper.shared.unauthorized import UnauthorizedError

_COMMAND_NAME = "AnswerInquiry"

_log = get_logger(__name__)


class Handler(Protocol):
    """The bare handler, before the wrapping the wire module applies."""

    async def __call__(
        self,
        command: AnswerInquiry,
        *,
        principal_id: UUID,
        correlation_id: UUID,
        causation_id: UUID | None = None,
        surface_id: UUID = NIL_SENTINEL_ID,
    ) -> None: ...


def bind(deps: Kernel) -> Handler:
    """Build the handler, closed over the process-wide dependencies."""

    async def handler(
        command: AnswerInquiry,
        *,
        principal_id: UUID,
        correlation_id: UUID,
        causation_id: UUID | None = None,
        surface_id: UUID = NIL_SENTINEL_ID,
    ) -> None:
        decision = await deps.authz.authorize(
            principal_id=principal_id,
            command_name=_COMMAND_NAME,
            surface_id=surface_id,
        )
        if isinstance(decision, Deny):
            _log.info(
                "answer_inquiry.denied",
                command_name=_COMMAND_NAME,
                inquiry_id=str(command.inquiry_id),
                principal_id=str(principal_id),
                correlation_id=str(correlation_id),
                reason=decision.reason,
            )
            raise UnauthorizedError(decision.reason)

        state, version = await load_inquiry_with_version(deps.event_store, command.inquiry_id)
        if command.proposal_id is not None:
            proposal = await load_proposal(deps.event_store, command.proposal_id)
            if proposal is None:
                raise ProposalNotFoundError(command.proposal_id)

        now = command.occurred_at if command.occurred_at is not None else deps.clock.now()
        events = decide(state, command, now=now)

        await deps.event_store.append(
            INQUIRY_STREAM_TYPE,
            command.inquiry_id,
            version,
            [
                to_new_event(
                    event_type=type(event).__name__,
                    payload=to_payload(event),
                    occurred_at=event.occurred_at,
                    event_id=deps.id_generator.new_id(),
                    command_name=_COMMAND_NAME,
                    correlation_id=correlation_id,
                    causation_id=causation_id,
                    principal_id=principal_id,
                )
                for event in events
            ],
        )

        _log.info(
            "answer_inquiry.success",
            command_name=_COMMAND_NAME,
            inquiry_id=str(command.inquiry_id),
            conclusion=command.conclusion.value,
            observed_step_count=command.observed_step_count,
            principal_id=str(principal_id),
            correlation_id=str(correlation_id),
        )

    return handler


__all__ = ["Handler", "bind"]
