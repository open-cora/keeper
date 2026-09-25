"""Register the device: authorize, decide, append.

Create-style on its own stream, so there is no load-and-fold and
`state=None` goes straight to the decider.

Nothing is loaded at all, which makes this the shortest handler in the
tree. Its two nearest neighbours both load a sibling first:
`register_dataset` loads the run that produced the data, and
`make_proposal` loads the plan whose schema it checks against. This
decision needs neither, because a device belongs to no run and satisfies
no schema.
"""

from typing import Protocol
from uuid import UUID

from keeper.equipment.aggregates.device import DEVICE_STREAM_TYPE, to_payload
from keeper.equipment.errors import UnauthorizedError
from keeper.equipment.features.register_device.command import RegisterDevice
from keeper.equipment.features.register_device.decider import decide
from keeper.infrastructure.kernel import Kernel
from keeper.infrastructure.logging import get_logger
from keeper.infrastructure.ports import Deny
from keeper.infrastructure.slices.envelope import to_new_event
from keeper.shared.reserved_ids import NIL_SENTINEL_ID

_COMMAND_NAME = "RegisterDevice"

_log = get_logger(__name__)


class Handler(Protocol):
    """The bare handler, before the wrapping the wire module applies."""

    async def __call__(
        self,
        command: RegisterDevice,
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
        command: RegisterDevice,
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
        command: RegisterDevice,
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
                "register_device.denied",
                command_name=_COMMAND_NAME,
                external_ref_scheme=command.external_ref.scheme,
                principal_id=str(principal_id),
                correlation_id=str(correlation_id),
                reason=decision.reason,
            )
            raise UnauthorizedError(decision.reason)

        new_id = deps.id_generator.new_id()
        events = decide(None, command, now=deps.clock.now(), new_id=new_id)

        await deps.event_store.append(
            DEVICE_STREAM_TYPE,
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
            "register_device.success",
            command_name=_COMMAND_NAME,
            device_id=str(new_id),
            external_ref_scheme=command.external_ref.scheme,
            principal_id=str(principal_id),
            correlation_id=str(correlation_id),
        )
        return new_id

    return handler


__all__ = ["Handler", "IdempotentHandler", "bind"]
