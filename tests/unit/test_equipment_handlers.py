"""The six Equipment handlers, against in-process stores.

One file for six handlers, because what is worth testing about them is
shared and small: this context reaches into no sibling, so there is no
cross-context load to get wrong and no 404 from somebody else's
aggregate. What is left is the part a decider never sees.

Three things, then. Which moment each handler stamps, which is R8
showing up as behaviour rather than as a field list. That a transition
appends at the version it folded from, which is the whole concurrency
story. And that every handler asks the authorization port first.
"""

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from keeper.equipment.adapters import InMemoryDeviceSummaryLookup
from keeper.equipment.aggregates.device import (
    DEVICE_STREAM_TYPE,
    DeviceCannotBeRecoveredError,
    DeviceName,
    DeviceNotFoundError,
    DeviceStatus,
    load_device,
)
from keeper.equipment.errors import UnauthorizedError
from keeper.equipment.features.fault_device import FaultDevice
from keeper.equipment.features.fault_device import bind as bind_fault
from keeper.equipment.features.get_device import GetDevice
from keeper.equipment.features.get_device import bind as bind_get
from keeper.equipment.features.list_devices import ListDevices
from keeper.equipment.features.list_devices import bind as bind_list
from keeper.equipment.features.recover_device import RecoverDevice
from keeper.equipment.features.recover_device import bind as bind_recover
from keeper.equipment.features.register_device import RegisterDevice
from keeper.equipment.features.register_device import bind as bind_register
from keeper.equipment.features.retire_device import RetireDevice
from keeper.equipment.features.retire_device import bind as bind_retire
from keeper.infrastructure.adapters.in_memory_event_store import InMemoryEventStore
from keeper.infrastructure.deps import make_inmemory_kernel
from keeper.infrastructure.kernel import Kernel
from keeper.infrastructure.ports import AllowAllAuthorize, Deny
from keeper.infrastructure.ports.authorize import AuthzResult
from keeper.infrastructure.settings import Settings
from keeper.shared.identifier import Identifier
from keeper.shared.reserved_ids import NIL_SENTINEL_ID

pytestmark = pytest.mark.unit

_CLOCK_NOW = datetime(2026, 9, 22, 9, 0, tzinfo=UTC)
"""What the clock says, deliberately not the time any caller reports."""
_REPORTED = datetime(2026, 9, 21, 6, 0, tzinfo=UTC)
_REF = Identifier(scheme="epics-prefix", value="2bmb:m1")


class _FixedClock:
    def now(self) -> datetime:
        return _CLOCK_NOW


class _Uuid4IdGenerator:
    def new_id(self) -> UUID:
        return uuid4()


class _DenyAllAuthorize:
    async def authorize(
        self,
        principal_id: UUID,
        command_name: str,
        surface_id: UUID = NIL_SENTINEL_ID,
    ) -> AuthzResult:
        _ = (principal_id, command_name, surface_id)
        return Deny(reason="not granted in this test")


def _kernel(*, authz: object | None = None) -> Kernel:
    return make_inmemory_kernel(
        settings=Settings(app_env="test"),
        clock=_FixedClock(),
        id_generator=_Uuid4IdGenerator(),
        authz=authz or AllowAllAuthorize(),  # pyright: ignore[reportArgumentType]
        event_store=InMemoryEventStore(),
    )


async def _a_device(deps: Kernel, *, value: str = "2bmb:m1") -> UUID:
    return await bind_register(deps)(
        RegisterDevice(
            external_ref=Identifier(scheme="epics-prefix", value=value),
            name=DeviceName("sample x translation"),
        ),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )


async def test_registering_writes_one_event_and_returns_its_id() -> None:
    deps = _kernel()

    device_id = await _a_device(deps)

    stored, _version = await deps.event_store.load(DEVICE_STREAM_TYPE, device_id)
    assert [row.event_type for row in stored] == ["DeviceRegistered"]


async def test_registering_stamps_the_clock_because_the_command_carries_no_time() -> None:
    """Enrolling is an act performed here, so the moment this system writes
    the record IS the moment it happened."""
    deps = _kernel()

    device_id = await _a_device(deps)

    stored, _version = await deps.event_store.load(DEVICE_STREAM_TYPE, device_id)
    assert stored[0].occurred_at == _CLOCK_NOW


async def test_a_reported_move_stamps_the_time_the_caller_gave() -> None:
    """A fault happened at a beamline at a moment nothing here was present
    for, so a caller who knows when is believed over the clock."""
    deps = _kernel()
    device_id = await _a_device(deps)

    await bind_fault(deps)(
        FaultDevice(device_id=device_id, occurred_at=_REPORTED),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )

    stored, _version = await deps.event_store.load(DEVICE_STREAM_TYPE, device_id)
    assert stored[1].occurred_at == _REPORTED


async def test_a_reported_move_without_a_time_falls_back_to_the_clock() -> None:
    """A caller saying nothing about when is answered with the moment the
    report arrived, which is the honest reading of an omitted field."""
    deps = _kernel()
    device_id = await _a_device(deps)

    await bind_fault(deps)(
        FaultDevice(device_id=device_id), principal_id=uuid4(), correlation_id=uuid4()
    )

    stored, _version = await deps.event_store.load(DEVICE_STREAM_TYPE, device_id)
    assert stored[1].occurred_at == _CLOCK_NOW


async def test_retiring_stamps_the_clock_and_accepts_no_reported_time() -> None:
    """R8 running between two commands on one stream: the fault above takes
    a time and this does not, because retiring happens here."""
    deps = _kernel()
    device_id = await _a_device(deps)

    await bind_retire(deps)(
        RetireDevice(device_id=device_id), principal_id=uuid4(), correlation_id=uuid4()
    )

    stored, _version = await deps.event_store.load(DEVICE_STREAM_TYPE, device_id)
    assert stored[1].occurred_at == _CLOCK_NOW
    assert "occurred_at" not in RetireDevice.__dataclass_fields__


async def test_a_full_life_lands_four_events_in_order_on_one_stream() -> None:
    deps = _kernel()
    device_id = await _a_device(deps)
    principal, cid = uuid4(), uuid4()

    await bind_fault(deps)(
        FaultDevice(device_id=device_id), principal_id=principal, correlation_id=cid
    )
    await bind_recover(deps)(
        RecoverDevice(device_id=device_id), principal_id=principal, correlation_id=cid
    )
    await bind_retire(deps)(
        RetireDevice(device_id=device_id), principal_id=principal, correlation_id=cid
    )

    stored, version = await deps.event_store.load(DEVICE_STREAM_TYPE, device_id)
    assert [row.event_type for row in stored] == [
        "DeviceRegistered",
        "DeviceFaulted",
        "DeviceRecovered",
        "DeviceRetired",
    ]
    assert version == 4, "each append lands at the version the handler folded from"


async def test_a_transition_the_state_forbids_is_refused_by_the_handler_path() -> None:
    """The decider's refusal reaching a caller through the handler, which
    is the path that actually loads the state it decides against."""
    deps = _kernel()
    device_id = await _a_device(deps)

    with pytest.raises(DeviceCannotBeRecoveredError) as refusal:
        await bind_recover(deps)(
            RecoverDevice(device_id=device_id), principal_id=uuid4(), correlation_id=uuid4()
        )

    assert refusal.value.status is DeviceStatus.AVAILABLE


async def test_a_move_against_an_unknown_device_is_not_found() -> None:
    deps = _kernel()

    with pytest.raises(DeviceNotFoundError):
        await bind_fault(deps)(
            FaultDevice(device_id=uuid4()), principal_id=uuid4(), correlation_id=uuid4()
        )


async def test_reading_an_unknown_device_is_not_found() -> None:
    deps = _kernel()

    with pytest.raises(DeviceNotFoundError):
        await bind_get(deps)(
            GetDevice(device_id=uuid4()), principal_id=uuid4(), correlation_id=uuid4()
        )


async def test_a_read_returns_the_state_the_fold_produced() -> None:
    deps = _kernel()
    device_id = await _a_device(deps)
    await bind_fault(deps)(
        FaultDevice(device_id=device_id), principal_id=uuid4(), correlation_id=uuid4()
    )

    device = await bind_get(deps)(
        GetDevice(device_id=device_id), principal_id=uuid4(), correlation_id=uuid4()
    )

    assert device == await load_device(deps.event_store, device_id)
    assert device.status is DeviceStatus.FAULTED


async def test_listing_by_address_returns_the_device_registered_there() -> None:
    """The first call any adapter makes, because ids are minted here and a
    reporter holds only the address."""
    deps = _kernel()
    wanted = await _a_device(deps, value="2bmb:m1")
    await _a_device(deps, value="2bmb:m2")
    summaries = InMemoryDeviceSummaryLookup(deps.event_store)  # pyright: ignore[reportArgumentType]

    page = await bind_list(deps, summaries)(
        ListDevices(external_ref=Identifier(scheme="epics-prefix", value="2bmb:m1")),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )

    assert [item.device_id for item in page.items] == [wanted]


@pytest.mark.parametrize(
    "call",
    [
        "register",
        "fault",
        "recover",
        "retire",
        "get",
        "list",
    ],
)
async def test_every_handler_asks_the_authorization_port_first(call: str) -> None:
    """A denial has to reach the caller before anything is read or written,
    which is what makes the port a gate rather than an audit line."""
    deps = _kernel(authz=_DenyAllAuthorize())
    device_id = uuid4()
    principal, cid = uuid4(), uuid4()

    with pytest.raises(UnauthorizedError):
        if call == "register":
            await bind_register(deps)(
                RegisterDevice(external_ref=_REF, name=DeviceName("a device")),
                principal_id=principal,
                correlation_id=cid,
            )
        elif call == "fault":
            await bind_fault(deps)(
                FaultDevice(device_id=device_id), principal_id=principal, correlation_id=cid
            )
        elif call == "recover":
            await bind_recover(deps)(
                RecoverDevice(device_id=device_id), principal_id=principal, correlation_id=cid
            )
        elif call == "retire":
            await bind_retire(deps)(
                RetireDevice(device_id=device_id), principal_id=principal, correlation_id=cid
            )
        elif call == "get":
            await bind_get(deps)(
                GetDevice(device_id=device_id), principal_id=principal, correlation_id=cid
            )
        else:
            summaries = InMemoryDeviceSummaryLookup(deps.event_store)  # pyright: ignore[reportArgumentType]
            await bind_list(deps, summaries)(
                ListDevices(), principal_id=principal, correlation_id=cid
            )


async def test_a_denied_transition_writes_nothing() -> None:
    """The gate runs before the load and the append, so a refused caller
    leaves no trace on the stream."""
    allowed = _kernel()
    device_id = await _a_device(allowed)
    denied = make_inmemory_kernel(
        settings=Settings(app_env="test"),
        clock=_FixedClock(),
        id_generator=_Uuid4IdGenerator(),
        authz=_DenyAllAuthorize(),  # pyright: ignore[reportArgumentType]
        event_store=allowed.event_store,
    )

    with pytest.raises(UnauthorizedError):
        await bind_fault(denied)(
            FaultDevice(device_id=device_id), principal_id=uuid4(), correlation_id=uuid4()
        )

    stored, _version = await allowed.event_store.load(DEVICE_STREAM_TYPE, device_id)
    assert [row.event_type for row in stored] == ["DeviceRegistered"]
