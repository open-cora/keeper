"""The Device aggregate: its four events, its fold, and the round trip.

Four events, so this is the first state machine in the tree with more
than one edge and the first with an edge that points backwards. The
properties worth pinning follow from that shape: every transition
reaches its own status, recovery returns to a status the device already
held, and none of the three moves anything but the status.

The round trip matters more here than it does next door. The genesis
re-validates two value objects on the way back out of the log, so a
payload that could not be built today has to fail on read rather than
become state nothing checked.
"""

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from keeper.equipment.aggregates.device import (
    Device,
    DeviceEvent,
    DeviceFaulted,
    DeviceName,
    DeviceRecovered,
    DeviceRegistered,
    DeviceRetired,
    DeviceStatus,
    InvalidDeviceNameError,
    evolve,
    fold,
    from_stored,
    to_payload,
)
from keeper.infrastructure.ports.event_store import StoredEvent
from keeper.shared.identifier import Identifier, InvalidIdentifierError

pytestmark = pytest.mark.unit

_WHEN = datetime(2026, 9, 22, 11, 15, tzinfo=UTC)
_REF = Identifier(scheme="epics-prefix", value="2bmb:m1")


def _registered(**overrides: object) -> DeviceRegistered:
    fields: dict[str, object] = {
        "device_id": uuid4(),
        "external_ref_scheme": _REF.scheme,
        "external_ref_value": _REF.value,
        "device_name": "sample x translation",
        "occurred_at": _WHEN,
    }
    fields.update(overrides)
    return DeviceRegistered(**fields)  # pyright: ignore[reportArgumentType]


def _stored(event: DeviceEvent) -> StoredEvent:
    return StoredEvent(
        position=1,
        event_id=uuid4(),
        stream_type="Device",
        stream_id=event.device_id,
        version=1,
        event_type=type(event).__name__,
        schema_version=1,
        payload=to_payload(event),
        correlation_id=uuid4(),
        causation_id=None,
        occurred_at=event.occurred_at,
        recorded_at=event.occurred_at,
    )


def test_folding_an_empty_stream_gives_nothing() -> None:
    assert fold([]) is None


def test_folding_a_genesis_gives_an_available_device() -> None:
    registered = _registered()

    state = fold([registered])

    assert state == Device(
        id=registered.device_id,
        external_ref=_REF,
        name=DeviceName("sample x translation"),
        status=DeviceStatus.AVAILABLE,
    )


def test_a_new_device_is_not_retired() -> None:
    assert fold([_registered()]).is_retired is False  # pyright: ignore[reportOptionalMemberAccess]


@pytest.mark.parametrize(
    ("transitions", "expected"),
    [
        ((DeviceFaulted,), DeviceStatus.FAULTED),
        ((DeviceFaulted, DeviceRecovered), DeviceStatus.AVAILABLE),
        ((DeviceRetired,), DeviceStatus.RETIRED),
        ((DeviceFaulted, DeviceRetired), DeviceStatus.RETIRED),
    ],
    ids=["faulted", "recovered", "retired", "retired-while-faulted"],
)
def test_each_path_through_the_machine_reaches_its_own_status(
    transitions: tuple[type[DeviceFaulted | DeviceRecovered | DeviceRetired], ...],
    expected: DeviceStatus,
) -> None:
    """Four paths rather than three, because retiring a faulted device is
    the ordinary way a broken thing leaves a register and a fold written as
    a forward-only chain would get it wrong."""
    registered = _registered()
    events: list[DeviceEvent] = [registered]
    events.extend(cls(device_id=registered.device_id, occurred_at=_WHEN) for cls in transitions)

    state = fold(events)

    assert state is not None
    assert state.status is expected


def test_recovery_returns_to_the_status_the_device_started_in() -> None:
    """The one edge on this machine that points backwards, so the status is
    not monotonic even though the stream only grows."""
    registered = _registered()
    device_id = registered.device_id

    statuses = [
        fold([registered]).status,  # pyright: ignore[reportOptionalMemberAccess]
        fold([registered, DeviceFaulted(device_id=device_id, occurred_at=_WHEN)]).status,  # pyright: ignore[reportOptionalMemberAccess]
        fold(
            [
                registered,
                DeviceFaulted(device_id=device_id, occurred_at=_WHEN),
                DeviceRecovered(device_id=device_id, occurred_at=_WHEN),
            ]
        ).status,  # pyright: ignore[reportOptionalMemberAccess]
    ]

    assert statuses == [
        DeviceStatus.AVAILABLE,
        DeviceStatus.FAULTED,
        DeviceStatus.AVAILABLE,
    ]


def test_only_retirement_is_terminal() -> None:
    assert DeviceStatus.RETIRED.is_terminal is True
    assert DeviceStatus.AVAILABLE.is_terminal is False
    assert DeviceStatus.FAULTED.is_terminal is False


def test_a_transition_leaves_every_other_field_unchanged() -> None:
    """A fault says nothing about where the device is or what it is called,
    so the fold must carry both through rather than rebuild them."""
    registered = _registered()

    state = fold([registered, DeviceFaulted(device_id=registered.device_id, occurred_at=_WHEN)])

    assert state is not None
    assert (state.id, state.external_ref, state.name) == (
        registered.device_id,
        _REF,
        DeviceName("sample x translation"),
    )


@pytest.mark.parametrize(
    "cls",
    [DeviceFaulted, DeviceRecovered, DeviceRetired],
    ids=["faulted", "recovered", "retired"],
)
def test_a_transition_before_a_genesis_is_a_broken_stream(
    cls: type[DeviceFaulted | DeviceRecovered | DeviceRetired],
) -> None:
    with pytest.raises(ValueError, match=cls.__name__):
        evolve(None, cls(device_id=uuid4(), occurred_at=_WHEN))


@pytest.mark.parametrize(
    "event",
    [
        _registered(),
        DeviceFaulted(device_id=uuid4(), occurred_at=_WHEN),
        DeviceRecovered(device_id=uuid4(), occurred_at=_WHEN),
        DeviceRetired(device_id=uuid4(), occurred_at=_WHEN),
    ],
    ids=["registered", "faulted", "recovered", "retired"],
)
def test_every_event_survives_the_trip_through_the_log(event: DeviceEvent) -> None:
    assert from_stored(_stored(event)) == event


@pytest.mark.parametrize(
    ("field", "error"),
    [
        ("external_ref_value", InvalidIdentifierError),
        ("device_name", InvalidDeviceNameError),
    ],
    ids=["reference", "label"],
)
def test_the_genesis_revalidates_its_value_objects_on_the_way_back(
    field: str, error: type[Exception]
) -> None:
    """Primitives in the log, value objects at the boundary. A payload that
    could not be constructed today has to fail on read rather than become
    state nothing checked.

    The error is the value object's own rather than one naming the event,
    and the split is worth knowing. `from_stored` wraps what IT raises, so
    a payload missing a key or holding a bad UUID comes back as a malformed
    `DeviceRegistered`. Re-validation happens a step later, in the fold,
    where the strings become value objects, and that step is outside the
    wrapper.
    """
    stored = _stored(_registered())
    stored.payload[field] = "   "

    with pytest.raises(error):
        evolve(None, from_stored(stored))


def test_a_payload_the_deserializer_cannot_read_names_the_event() -> None:
    """The other half of the split above: what `from_stored` raises IS
    wrapped, so the message names the event and echoes no payload."""
    stored = _stored(_registered())
    stored.payload["device_id"] = "not-a-uuid"

    with pytest.raises(ValueError, match="DeviceRegistered"):
        from_stored(stored)


def test_an_unknown_event_type_is_refused_rather_than_ignored() -> None:
    stored = _stored(_registered())
    stored.payload["device_id"] = str(UUID(int=1))
    broken = StoredEvent(
        position=stored.position,
        event_id=stored.event_id,
        stream_type=stored.stream_type,
        stream_id=stored.stream_id,
        version=stored.version,
        event_type="DeviceExploded",
        schema_version=stored.schema_version,
        payload=stored.payload,
        correlation_id=stored.correlation_id,
        causation_id=stored.causation_id,
        occurred_at=stored.occurred_at,
        recorded_at=stored.recorded_at,
    )

    with pytest.raises(ValueError, match="DeviceExploded"):
        from_stored(broken)
