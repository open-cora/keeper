"""Run the definition: authorize, decide, append.

Create-style shape. A freshly minted id provably has no history, so this
handler skips the load-and-fold that an editing handler starts with and
hands `state=None` straight to the decider.

One store is written, so there is no ordering to get right and no window
in which a crash leaves two stores disagreeing about the same policy.

The authorization call is not a special case here. Defining a policy is
gated by whatever policy the deployment is already running, exactly like
every other command; a deployment with no policy yet is running
`AllowAllAuthorize`, which is what makes the first definition possible.
The principal recorded on the event is whoever performed it, which under
that posture is the system principal. That is a different field from the
principals named INSIDE the permissions, and only the latter are being
granted anything.
"""

from typing import Protocol
from uuid import UUID

from keeper.authority.aggregates.policy import POLICY_STREAM_TYPE, to_payload
from keeper.authority.errors import UnauthorizedError
from keeper.authority.features.define_policy.command import DefinePolicy
from keeper.authority.features.define_policy.decider import decide
from keeper.infrastructure.kernel import Kernel
from keeper.infrastructure.logging import get_logger
from keeper.infrastructure.ports import Deny
from keeper.infrastructure.slices.envelope import to_new_event
from keeper.shared.reserved_ids import NIL_SENTINEL_ID

_COMMAND_NAME = "DefinePolicy"

_log = get_logger(__name__)


class Handler(Protocol):
    """The bare handler, before the wrapping the wire module applies."""

    async def __call__(
        self,
        command: DefinePolicy,
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
        command: DefinePolicy,
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
        command: DefinePolicy,
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
                "define_policy.denied",
                command_name=_COMMAND_NAME,
                principal_id=str(principal_id),
                correlation_id=str(correlation_id),
                reason=decision.reason,
            )
            raise UnauthorizedError(decision.reason)

        new_id = deps.id_generator.new_id()
        now = deps.clock.now()
        events = decide(None, command, now=now, new_id=new_id)

        await deps.event_store.append(
            POLICY_STREAM_TYPE,
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
            "define_policy.success",
            command_name=_COMMAND_NAME,
            policy_id=str(new_id),
            permission_count=len(command.permissions),
            principal_id=str(principal_id),
            correlation_id=str(correlation_id),
        )
        return new_id

    return handler


__all__ = ["Handler", "IdempotentHandler", "bind"]
