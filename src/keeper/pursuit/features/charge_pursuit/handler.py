"""Charge the pursuit: authorize, load, decide, append at the version folded.

Returns the pursuit's total in the charged dimension afterwards, which is
two things at once. It is what a reporter wants back, since the number it
sent was a delta and the number it cares about is where the budget now
stands. And it is what lets this handler be wrapped for retries at all:
`with_idempotency` cannot carry a result of None, because a stored None is
indistinguishable from nothing stored, so a handler that answered with
nothing would silently get no replay protection.

That matters here more than anywhere else in this context. Charges add
rather than replace, so a redelivered one is not a repeat that changes
nothing: it is beam time spent twice on a record that cannot be edited.
"""

from typing import Protocol
from uuid import UUID

from keeper.infrastructure.kernel import Kernel
from keeper.infrastructure.logging import get_logger
from keeper.infrastructure.ports import Deny
from keeper.infrastructure.slices.envelope import to_new_event
from keeper.pursuit.aggregates.pursuit import (
    PURSUIT_STREAM_TYPE,
    PursuitNotFoundError,
    load_pursuit_with_version,
    to_payload,
)
from keeper.pursuit.features.charge_pursuit.command import ChargePursuit
from keeper.pursuit.features.charge_pursuit.decider import decide
from keeper.shared.reserved_ids import NIL_SENTINEL_ID
from keeper.shared.unauthorized import UnauthorizedError

_COMMAND_NAME = "ChargePursuit"

_log = get_logger(__name__)


class Handler(Protocol):
    """The bare handler, before the wrapping the wire module applies."""

    async def __call__(
        self,
        command: ChargePursuit,
        *,
        principal_id: UUID,
        correlation_id: UUID,
        causation_id: UUID | None = None,
        surface_id: UUID = NIL_SENTINEL_ID,
    ) -> int: ...


class IdempotentHandler(Protocol):
    """The same handler once the idempotency wrapper is around it.

    One extra keyword. None means behave exactly like the bare handler,
    which is what every caller without a retry key gets, and here that is
    a caller accepting that a retry charges twice.
    """

    async def __call__(
        self,
        command: ChargePursuit,
        *,
        principal_id: UUID,
        correlation_id: UUID,
        causation_id: UUID | None = None,
        surface_id: UUID = NIL_SENTINEL_ID,
        idempotency_key: str | None = None,
    ) -> int: ...


def bind(deps: Kernel) -> Handler:
    """Build the handler, closed over the process-wide dependencies."""

    async def handler(
        command: ChargePursuit,
        *,
        principal_id: UUID,
        correlation_id: UUID,
        causation_id: UUID | None = None,
        surface_id: UUID = NIL_SENTINEL_ID,
    ) -> int:
        decision = await deps.authz.authorize(
            principal_id=principal_id,
            command_name=_COMMAND_NAME,
            surface_id=surface_id,
        )
        if isinstance(decision, Deny):
            _log.info(
                "charge_pursuit.denied",
                command_name=_COMMAND_NAME,
                pursuit_id=str(command.pursuit_id),
                dimension=command.dimension.value,
                principal_id=str(principal_id),
                correlation_id=str(correlation_id),
                reason=decision.reason,
            )
            raise UnauthorizedError(decision.reason)

        pursuit, version = await load_pursuit_with_version(deps.event_store, command.pursuit_id)
        if pursuit is None:
            raise PursuitNotFoundError(command.pursuit_id)

        events = decide(pursuit, command, now=deps.clock.now())

        await deps.event_store.append(
            PURSUIT_STREAM_TYPE,
            command.pursuit_id,
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

        total = pursuit.charged.get(command.dimension, 0) + command.amount
        _log.info(
            "charge_pursuit.success",
            command_name=_COMMAND_NAME,
            pursuit_id=str(command.pursuit_id),
            dimension=command.dimension.value,
            amount=command.amount,
            total=total,
            principal_id=str(principal_id),
            correlation_id=str(correlation_id),
        )
        return total

    return handler


__all__ = ["Handler", "IdempotentHandler", "bind"]
