"""Make the proposal: authorize, check the plan, decide, append.

Create-style on its own stream, so there is no load-and-fold of a
proposal and `state=None` goes straight to the decider.

The plan is loaded and handed across on a context, which is
`define_procedure`'s shape rather than `register_dataset`'s. The
difference is what the decision needs: registering a dataset checks only
that the step exists, so nothing crosses; this decision reads the plan's
schema, so the plan is an input and travels as plain data.

`PlanNotFoundError` is Execution's class, raised from here. It is not
re-registered on Counsel's routes: FastAPI's exception handlers are
app-scoped and Execution already maps it to 404, which is the rule in
docs/reference/patterns.md for a cross-BC domain error.

The principal becomes the proposer. That is the one place this handler
does more than plumb, and it is deliberate: a caller that could name its
own `actor_id` could advise as somebody else, so the field is taken from
the authenticated identity the authorization port just checked.
"""

from typing import Protocol
from uuid import UUID

from keeper.counsel.aggregates.proposal import PROPOSAL_STREAM_TYPE, to_payload
from keeper.counsel.errors import UnauthorizedError
from keeper.counsel.features.make_proposal.command import MakeProposal
from keeper.counsel.features.make_proposal.context import MakeProposalContext
from keeper.counsel.features.make_proposal.decider import decide
from keeper.execution.aggregates.plan import PlanNotFoundError, load_plan
from keeper.infrastructure.kernel import Kernel
from keeper.infrastructure.logging import get_logger
from keeper.infrastructure.ports import Deny
from keeper.infrastructure.slices.envelope import to_new_event
from keeper.shared.reserved_ids import NIL_SENTINEL_ID

_COMMAND_NAME = "MakeProposal"

_log = get_logger(__name__)


class Handler(Protocol):
    """The bare handler, before the wrapping the wire module applies."""

    async def __call__(
        self,
        command: MakeProposal,
        *,
        principal_id: UUID,
        correlation_id: UUID,
        causation_id: UUID | None = None,
        surface_id: UUID = NIL_SENTINEL_ID,
    ) -> UUID: ...


class IdempotentHandler(Protocol):
    """The same handler once the idempotency wrapper is around it.

    One extra keyword. None means behave exactly like the bare handler,
    which is what every caller without a retry key gets.
    """

    async def __call__(
        self,
        command: MakeProposal,
        *,
        principal_id: UUID,
        correlation_id: UUID,
        causation_id: UUID | None = None,
        surface_id: UUID = NIL_SENTINEL_ID,
        idempotency_key: str | None = None,
    ) -> UUID: ...


def bind(deps: Kernel) -> Handler:
    """Build the handler, closed over the process-wide dependencies."""

    async def handler(
        command: MakeProposal,
        *,
        principal_id: UUID,
        correlation_id: UUID,
        causation_id: UUID | None = None,
        surface_id: UUID = NIL_SENTINEL_ID,
    ) -> UUID:
        decision = await deps.authz.authorize(
            principal_id=principal_id,
            command_name=_COMMAND_NAME,
            surface_id=surface_id,
        )
        if isinstance(decision, Deny):
            _log.info(
                "make_proposal.denied",
                command_name=_COMMAND_NAME,
                plan_id=str(command.plan_id),
                principal_id=str(principal_id),
                correlation_id=str(correlation_id),
                reason=decision.reason,
            )
            raise UnauthorizedError(decision.reason)

        plan = await load_plan(deps.event_store, command.plan_id)
        if plan is None:
            raise PlanNotFoundError(command.plan_id)

        new_id = deps.id_generator.new_id()
        events = decide(
            None,
            command,
            context=MakeProposalContext(plan=plan),
            actor_id=principal_id,
            now=deps.clock.now(),
            new_id=new_id,
        )

        await deps.event_store.append(
            PROPOSAL_STREAM_TYPE,
            new_id,
            0,
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
            "make_proposal.success",
            command_name=_COMMAND_NAME,
            proposal_id=str(new_id),
            plan_id=str(command.plan_id),
            principal_id=str(principal_id),
            correlation_id=str(correlation_id),
        )
        return new_id

    return handler


__all__ = ["Handler", "IdempotentHandler", "bind"]
