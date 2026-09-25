"""Answer the question: authorize, load, return.

No decider, no append, no clock. A read produces no events, so there is
nothing for a pure decision function to decide and nothing to make
reproducible on replay.

Authorization still happens. A plan says what this system can be asked to
run and what each request has to look like, so a caller who can read one
learns the shape of a command they may not be permitted to send.

`PlanNotFoundError` rather than a `None` return. The aggregate's
`load_plan` returns None and leaves the meaning to its caller, which is
this handler: both surfaces want a refusal, and raising the same error
the writing slice raises gets it mapped in one place instead of two.
"""

from typing import Protocol
from uuid import UUID

from keeper.execution.aggregates.plan import Plan, PlanNotFoundError, load_plan
from keeper.execution.errors import UnauthorizedError
from keeper.execution.features.get_plan.query import GetPlan
from keeper.infrastructure.kernel import Kernel
from keeper.infrastructure.logging import get_logger
from keeper.infrastructure.ports import Deny
from keeper.shared.reserved_ids import NIL_SENTINEL_ID

_COMMAND_NAME = "GetPlan"

_log = get_logger(__name__)


class Handler(Protocol):
    """The bare handler, before the wrapping the wire module applies."""

    async def __call__(
        self,
        query: GetPlan,
        *,
        principal_id: UUID,
        correlation_id: UUID,
        causation_id: UUID | None = None,
        surface_id: UUID = NIL_SENTINEL_ID,
    ) -> Plan: ...


def bind(deps: Kernel) -> Handler:
    """Build the handler, closed over the process-wide dependencies."""

    async def handler(
        query: GetPlan,
        *,
        principal_id: UUID,
        correlation_id: UUID,
        causation_id: UUID | None = None,
        surface_id: UUID = NIL_SENTINEL_ID,
    ) -> Plan:
        _ = causation_id
        decision = await deps.authz.authorize(
            principal_id=principal_id,
            command_name=_COMMAND_NAME,
            surface_id=surface_id,
        )
        if isinstance(decision, Deny):
            _log.info(
                "get_plan.denied",
                command_name=_COMMAND_NAME,
                plan_id=str(query.plan_id),
                principal_id=str(principal_id),
                correlation_id=str(correlation_id),
                reason=decision.reason,
            )
            raise UnauthorizedError(decision.reason)

        plan = await load_plan(deps.event_store, query.plan_id)
        if plan is None:
            raise PlanNotFoundError(query.plan_id)
        return plan

    return handler


__all__ = ["Handler", "bind"]
