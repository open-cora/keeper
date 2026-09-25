"""The decision that enrols a device.

One invariant, which is the honest count: this context holds a reference
to something it cannot reach, so there is nothing here to check it
against. What the decider CANNOT see is worth pinning as much as what it
refuses, because the gap it leaves is the one an adapter meets first.
"""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from keeper.equipment.aggregates.device import (
    Device,
    DeviceAlreadyExistsError,
    DeviceName,
    DeviceRegistered,
    DeviceStatus,
)
from keeper.equipment.features.register_device import RegisterDevice, decide
from keeper.shared.identifier import Identifier

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 9, 22, 11, 15, tzinfo=UTC)
_REF = Identifier(scheme="epics-prefix", value="2bmb:m1")


def _command(**overrides: object) -> RegisterDevice:
    fields: dict[str, object] = {
        "external_ref": _REF,
        "name": DeviceName("sample x translation"),
    }
    fields.update(overrides)
    return RegisterDevice(**fields)  # pyright: ignore[reportArgumentType]


def test_registering_produces_one_event_carrying_the_address_and_the_label() -> None:
    new_id = uuid4()

    events = decide(None, _command(), now=_NOW, new_id=new_id)

    assert events == [
        DeviceRegistered(
            device_id=new_id,
            external_ref_scheme="epics-prefix",
            external_ref_value="2bmb:m1",
            device_name="sample x translation",
            occurred_at=_NOW,
        )
    ]


def test_the_event_carries_the_id_the_handler_minted_not_one_it_invented() -> None:
    """A decider that minted its own id would decide differently on every
    replay, which is the property the whole approach rests on."""
    new_id = uuid4()

    (event,) = decide(None, _command(), now=_NOW, new_id=new_id)

    assert event.device_id == new_id


def test_the_time_is_the_one_passed_in_because_the_command_carries_none() -> None:
    """Enrolling is an act performed here, so there is no earlier moment
    for the record to be late to and no field for a caller to supply one."""
    (event,) = decide(None, _command(), now=_NOW, new_id=uuid4())

    assert event.occurred_at == _NOW


def test_the_reference_is_flattened_into_two_strings() -> None:
    """Events carry primitives; the pair is rebuilt by the fold."""
    (event,) = decide(None, _command(), now=_NOW, new_id=uuid4())

    assert (event.external_ref_scheme, event.external_ref_value) == ("epics-prefix", "2bmb:m1")


def test_registering_onto_a_live_stream_is_refused() -> None:
    """Unreachable through the ordinary path, because the handler mints a
    fresh id. It is stated so the decider does not assume it."""
    existing = Device(
        id=uuid4(),
        external_ref=_REF,
        name=DeviceName("already here"),
        status=DeviceStatus.AVAILABLE,
    )

    with pytest.raises(DeviceAlreadyExistsError) as refusal:
        decide(existing, _command(), now=_NOW, new_id=uuid4())

    assert refusal.value.device_id == existing.id


def test_a_second_device_at_the_same_address_is_not_refused_here() -> None:
    """The gap an adapter meets first, pinned so it is a decision rather
    than an oversight. Nothing in a decider can see another stream, so two
    records of one motor are made and nothing notices. Closing it needs a
    cross-stream pattern; what this context does instead is let the read
    side show both.
    """
    events = decide(None, _command(), now=_NOW, new_id=uuid4())

    assert len(events) == 1
