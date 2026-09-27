"""Make the inquiry: authorize, load the execution, decide, append.

Create-style on its own stream, so there is no load-and-fold of an inquiry
and `state=None` goes straight to the decider.

The execution is loaded and handed across on a context, which is
`make_proposal`'s shape. The difference is what the decision takes off it:
that one reads a plan's schema, and this one counts the steps the execution
was dispatched with. Both are data the decider needs and neither is
something a pure function can go and fetch.

`ExecutionNotFoundError` is Execution's class, raised from here. It is not
re-registered on Counsel's routes: FastAPI's exception handlers are
app-scoped and Execution already maps it to 404, which is the rule in
docs/reference/patterns.md for a cross-BC domain error.

The principal becomes the asker. That is the one place this handler does
more than plumb, and it is deliberate: a caller that could name its own
`actor_id` could ask as somebody else.
"""

from typing import Protocol
from uuid import UUID

from keeper.counsel.aggregates.inquiry import INQUIRY_STREAM_TYPE, to_payload
from keeper.counsel.features.make_inquiry.command import MakeInquiry
from keeper.counsel.features.make_inquiry.context import MakeInquiryContext
from keeper.counsel.features.make_inquiry.decider import decide
from keeper.execution.aggregates.execution import ExecutionNotFoundError, load_execution
from keeper.infrastructure.kernel import Kernel
from keeper.infrastructure.logging import get_logger
from keeper.infrastructure.ports import Deny
from keeper.infrastructure.slices.envelope import to_new_event
from keeper.shared.reserved_ids import NIL_SENTINEL_ID
from keeper.shared.unauthorized import UnauthorizedError

_COMMAND_NAME = "MakeInquiry"

_log = get_logger(__name__)


class Handler(Protocol):
    """The bare handler, before the wrapping the wire module applies."""

    async def __call__(
        self,
        command: MakeInquiry,
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
        command: MakeInquiry,
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
        command: MakeInquiry,
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
                "make_inquiry.denied",
                command_name=_COMMAND_NAME,
                execution_id=str(command.execution_id),
                principal_id=str(principal_id),
                correlation_id=str(correlation_id),
                reason=decision.reason,
            )
            raise UnauthorizedError(decision.reason)

        execution = await load_execution(deps.event_store, command.execution_id)
        if execution is None:
            raise ExecutionNotFoundError(command.execution_id)

        new_id = deps.id_generator.new_id()
        events = decide(
            None,
            command,
            context=MakeInquiryContext(execution=execution),
            actor_id=principal_id,
            now=deps.clock.now(),
            new_id=new_id,
        )

        await deps.event_store.append(
            INQUIRY_STREAM_TYPE,
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
            "make_inquiry.success",
            command_name=_COMMAND_NAME,
            inquiry_id=str(new_id),
            execution_id=str(command.execution_id),
            principal_id=str(principal_id),
            correlation_id=str(correlation_id),
        )
        return new_id

    return handler


__all__ = ["Handler", "IdempotentHandler", "bind"]
