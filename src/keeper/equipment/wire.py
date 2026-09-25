"""Compose the Equipment handlers from the process-wide dependencies.

`wire_equipment(deps)` runs once during startup and the bundle it
returns is attached to the app. Routes and MCP tools both pull their
handler out of that bundle, which is what keeps the two surfaces calling
the same code rather than two copies of it.

Wrapping order, innermost first:

  1. bind          the bare handler
  2. idempotency   a replayed key returns the first answer instead of
                   registering a second device
  3. tracing       one span per call, whether or not the key hit cache

Idempotency wraps inside tracing on purpose: a cache hit is still a call
somebody made and should still appear in a trace.

Only the genesis takes the middle layer. Registering a device mints an
id on the server, so a retry with no key would leave a second record of
one motor, and a second record of one motor is the duplicate this
context can least afford: an adapter resolving an address to fault it
would find two and have to choose. The three transitions go without,
because a replayed transition is already refused by the domain and the
wrapper would buy a friendlier status code rather than prevent a
duplicate. The two reads go without because there is nothing in a read
to make idempotent.

One slice takes more than the kernel. `list_devices` reads a projection,
which the kernel cannot hold because the kernel is declared in
infrastructure and a device summary is Equipment's own idea, so this
module picks the implementation and passes it in.
"""

from dataclasses import dataclass
from uuid import UUID

from keeper.equipment.adapters import (
    InMemoryDeviceSummaryLookup,
    PostgresDeviceSummaryLookup,
)
from keeper.equipment.aggregates.device.summary import DeviceSummaryLookup
from keeper.equipment.features import (
    fault_device,
    get_device,
    list_devices,
    recover_device,
    register_device,
    retire_device,
)
from keeper.infrastructure.adapters.in_memory_event_store import InMemoryEventStore
from keeper.infrastructure.kernel import Kernel
from keeper.infrastructure.observability import with_tracing
from keeper.infrastructure.slices.idempotency import with_idempotency

_BC = "equipment"


class UnreadableSummariesError(RuntimeError):
    """Startup found no way to read this context's summaries.

    Raised when there is neither a connection pool nor the in-memory
    event store, which is a combination no supported environment
    produces and a new adapter could. Failing here rather than at the
    first request is the point: a deployment that cannot answer a query
    should not finish booting and look healthy.

    The fourth class with this name and this body, one per context that
    has a read model. Its siblings each said the next one to need it is
    the trigger to hoist, and each then declined for the reason they
    gave: a landing that adds a read model should not also reshape the
    ones beside it. The move is its own commit and is now three landings
    overdue, alongside `UnauthorizedError`.
    """

    def __init__(self, event_store: str) -> None:
        super().__init__(
            f"No pool and no in-memory event store ({event_store}), so nothing "
            "can answer a summary query"
        )
        self.event_store = event_store


@dataclass(frozen=True)
class EquipmentHandlers:
    """The bundle, one field per slice."""

    register_device: register_device.IdempotentHandler
    fault_device: fault_device.Handler
    recover_device: recover_device.Handler
    retire_device: retire_device.Handler
    get_device: get_device.Handler
    list_devices: list_devices.Handler


def _device_summary_lookup(deps: Kernel) -> DeviceSummaryLookup:
    """Pick the read adapter this deployment can actually use.

    With a pool, the projection table, which a background worker keeps
    in step. Without one, a fold over every device stream, because the
    worker does not run when there is nothing to project into and an
    empty table would answer "no device at that address" to a reporter
    about to register a second one.
    """
    if deps.pool is not None:
        return PostgresDeviceSummaryLookup(deps.pool)
    if isinstance(deps.event_store, InMemoryEventStore):
        return InMemoryDeviceSummaryLookup(deps.event_store)
    raise UnreadableSummariesError(type(deps.event_store).__name__)


def wire_equipment(deps: Kernel) -> EquipmentHandlers:
    """Build the Equipment handlers."""
    return EquipmentHandlers(
        register_device=with_tracing(
            with_idempotency(
                register_device.bind(deps),
                deps.idempotency_store,
                command_name="RegisterDevice",
                serialize_result=str,
                deserialize_result=lambda raw: UUID(str(raw)),
                lock_stale_seconds=deps.settings.idempotency_lock_stale_seconds,
            ),
            command_name="RegisterDevice",
            bc=_BC,
        ),
        fault_device=with_tracing(
            fault_device.bind(deps),
            command_name="FaultDevice",
            bc=_BC,
        ),
        recover_device=with_tracing(
            recover_device.bind(deps),
            command_name="RecoverDevice",
            bc=_BC,
        ),
        retire_device=with_tracing(
            retire_device.bind(deps),
            command_name="RetireDevice",
            bc=_BC,
        ),
        get_device=with_tracing(
            get_device.bind(deps),
            command_name="GetDevice",
            bc=_BC,
        ),
        list_devices=with_tracing(
            list_devices.bind(deps, _device_summary_lookup(deps)),
            command_name="ListDevices",
            bc=_BC,
        ),
    )


__all__ = ["EquipmentHandlers", "UnreadableSummariesError", "wire_equipment"]
