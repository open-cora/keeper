"""Answer the question: authorize, load, return.

No decider, no append, no clock. A read produces no events, so there is
nothing for a pure decision function to decide and nothing to make
reproducible on replay.

Authorization still happens. A page of devices and their states is a
picture of what a facility has and what is broken on it, which is more
than a deployment necessarily wants every caller to learn.

`DeviceNotFoundError` rather than a `None` return. The aggregate's
`load_device` returns None and leaves the meaning to its caller, which
is this handler: both surfaces want a refusal, and raising the same
error shape the sibling contexts raise gets it mapped in one place
instead of two.
"""

from typing import Protocol
from uuid import UUID

from keeper.equipment.aggregates.device import Device, DeviceNotFoundError, load_device
from keeper.equipment.errors import UnauthorizedError
from keeper.equipment.features.get_device.query import GetDevice
from keeper.infrastructure.kernel import Kernel
from keeper.infrastructure.logging import get_logger
from keeper.infrastructure.ports import Deny
from keeper.shared.reserved_ids import NIL_SENTINEL_ID

_COMMAND_NAME = "GetDevice"

_log = get_logger(__name__)


class Handler(Protocol):
    """The bare handler, before the wrapping the wire module applies."""

    async def __call__(
        self,
        query: GetDevice,
        *,
        principal_id: UUID,
        correlation_id: UUID,
        causation_id: UUID | None = None,
        surface_id: UUID = NIL_SENTINEL_ID,
    ) -> Device: ...


def bind(deps: Kernel) -> Handler:
    """Build the handler, closed over the process-wide dependencies."""

    async def handler(
        query: GetDevice,
        *,
        principal_id: UUID,
        correlation_id: UUID,
        causation_id: UUID | None = None,
        surface_id: UUID = NIL_SENTINEL_ID,
    ) -> Device:
        _ = causation_id
        decision = await deps.authz.authorize(
            principal_id=principal_id,
            command_name=_COMMAND_NAME,
            surface_id=surface_id,
        )
        if isinstance(decision, Deny):
            _log.info(
                "get_device.denied",
                command_name=_COMMAND_NAME,
                device_id=str(query.device_id),
                principal_id=str(principal_id),
                correlation_id=str(correlation_id),
                reason=decision.reason,
            )
            raise UnauthorizedError(decision.reason)

        device = await load_device(deps.event_store, query.device_id)
        if device is None:
            raise DeviceNotFoundError(query.device_id)
        return device

    return handler


__all__ = ["Handler", "bind"]
