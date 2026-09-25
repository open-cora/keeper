"""The three decisions that move a device, in one file.

One file for three deciders, the way the run endings share one, because
what is worth testing about them is shared: each names a stream that
exists, each refuses from a state the machine does not allow, and each
carries the status on the refusal so a caller learns what it did not
know.

What is NOT shared is which states each refuses from, and that is the
table below. It is written out per verb rather than derived, because a
table that computed the expected refusals from the same rule the
deciders use would agree with them by construction.
"""

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from keeper.equipment.aggregates.device import (
    Device,
    DeviceCannotBeFaultedError,
    DeviceCannotBeRecoveredError,
    DeviceCannotBeRetiredError,
    DeviceFaulted,
    DeviceName,
    DeviceNotFoundError,
    DeviceRecovered,
    DeviceRegistered,
    DeviceRetired,
    DeviceStatus,
)
from keeper.equipment.features.fault_device import FaultDevice
from keeper.equipment.features.fault_device import decide as decide_fault
from keeper.equipment.features.recover_device import RecoverDevice
from keeper.equipment.features.recover_device import decide as decide_recover
from keeper.equipment.features.retire_device import RetireDevice
from keeper.equipment.features.retire_device import decide as decide_retire
from keeper.shared.identifier import Identifier

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 9, 22, 11, 15, tzinfo=UTC)
_REF = Identifier(scheme="epics-prefix", value="2bmb:m1")


def _device(status: DeviceStatus, device_id: UUID | None = None) -> Device:
    return Device(
        id=device_id or uuid4(),
        external_ref=_REF,
        name=DeviceName("sample x translation"),
        status=status,
    )


def test_faulting_an_available_device_produces_one_event() -> None:
    device = _device(DeviceStatus.AVAILABLE)

    events = decide_fault(device, FaultDevice(device_id=device.id, occurred_at=_NOW), now=_NOW)

    assert events == [DeviceFaulted(device_id=device.id, occurred_at=_NOW)]


def test_recovering_a_faulted_device_produces_one_event() -> None:
    device = _device(DeviceStatus.FAULTED)

    events = decide_recover(device, RecoverDevice(device_id=device.id, occurred_at=_NOW), now=_NOW)

    assert events == [DeviceRecovered(device_id=device.id, occurred_at=_NOW)]


def test_retiring_an_available_device_produces_one_event() -> None:
    device = _device(DeviceStatus.AVAILABLE)

    events = decide_retire(device, RetireDevice(device_id=device.id), now=_NOW)

    assert events == [DeviceRetired(device_id=device.id, occurred_at=_NOW)]


def test_retiring_a_faulted_device_is_allowed() -> None:
    """The ordinary way a broken thing leaves a register. Nothing requires
    it to be recovered first, and a machine that did would strand every
    device that broke and stayed broken.
    """
    device = _device(DeviceStatus.FAULTED)

    events = decide_retire(device, RetireDevice(device_id=device.id), now=_NOW)

    assert events == [DeviceRetired(device_id=device.id, occurred_at=_NOW)]


@pytest.mark.parametrize(
    ("verb", "status"),
    [
        ("fault", DeviceStatus.FAULTED),
        ("fault", DeviceStatus.RETIRED),
        ("recover", DeviceStatus.AVAILABLE),
        ("recover", DeviceStatus.RETIRED),
        ("retire", DeviceStatus.RETIRED),
    ],
    ids=[
        "fault-a-faulted-device",
        "fault-a-retired-device",
        "recover-an-available-device",
        "recover-a-retired-device",
        "retire-a-retired-device",
    ],
)
def test_every_move_the_machine_does_not_allow_is_refused(verb: str, status: DeviceStatus) -> None:
    device = _device(status)
    errors = {
        "fault": DeviceCannotBeFaultedError,
        "recover": DeviceCannotBeRecoveredError,
        "retire": DeviceCannotBeRetiredError,
    }

    with pytest.raises(errors[verb]) as refusal:
        if verb == "fault":
            decide_fault(device, FaultDevice(device_id=device.id), now=_NOW)
        elif verb == "recover":
            decide_recover(device, RecoverDevice(device_id=device.id), now=_NOW)
        else:
            decide_retire(device, RetireDevice(device_id=device.id), now=_NOW)

    assert refusal.value.status is status, (
        "the status is the fact the caller did not have, so it rides on the "
        "refusal rather than being left for a second call to discover"
    )
    assert refusal.value.device_id == device.id


@pytest.mark.parametrize("verb", ["fault", "recover", "retire"], ids=["fault", "recover", "retire"])
def test_a_move_against_a_device_that_was_never_registered_is_not_found(verb: str) -> None:
    """None means no such stream, which is a 404 rather than a refusal: the
    caller named nothing rather than asking for something disallowed."""
    device_id = uuid4()

    with pytest.raises(DeviceNotFoundError) as missing:
        if verb == "fault":
            decide_fault(None, FaultDevice(device_id=device_id), now=_NOW)
        elif verb == "recover":
            decide_recover(None, RecoverDevice(device_id=device_id), now=_NOW)
        else:
            decide_retire(None, RetireDevice(device_id=device_id), now=_NOW)

    assert missing.value.device_id == device_id


def test_a_duplicate_fault_is_refused_rather_than_absorbed() -> None:
    """A domain claim rather than a safety rail. Faults reach only whoever
    was subscribed when they happened, so two reporters watching one device
    is a real configuration and a second report is far likelier to be a
    redelivery than a new fault. Recording it would leave a later reader
    counting outages that did not happen.
    """
    device = _device(DeviceStatus.FAULTED)

    with pytest.raises(DeviceCannotBeFaultedError):
        decide_fault(device, FaultDevice(device_id=device.id), now=_NOW)


def test_an_unmatched_recovery_is_refused_rather_than_absorbed() -> None:
    """The likelier of the two, because a reporter that restarted missed
    the fault. Absorbing it would let a stream carry an ending with no
    beginning, and the honest repair is to report the fault.
    """
    device = _device(DeviceStatus.AVAILABLE)

    with pytest.raises(DeviceCannotBeRecoveredError) as refusal:
        decide_recover(device, RecoverDevice(device_id=device.id), now=_NOW)

    assert refusal.value.status is DeviceStatus.AVAILABLE


def test_the_two_reported_moves_stamp_the_time_they_are_given() -> None:
    """A fault happened at a beamline, so the moment is the caller's and
    the handler is what chooses between it and the clock. The decider is
    handed one value and uses it.
    """
    device = _device(DeviceStatus.AVAILABLE)
    reported = datetime(2026, 9, 21, 3, 0, tzinfo=UTC)

    (faulted,) = decide_fault(device, FaultDevice(device_id=device.id), now=reported)

    assert faulted.occurred_at == reported


def test_nothing_on_a_transition_says_who_reported_it_or_why() -> None:
    """No severity, no reason, no reporter. The first because a fault is
    the reporter's judgement and a number invites re-deriving it; the
    second because free text from a control system is where a person's
    name arrives; the third because the principal is on the envelope.
    """
    device = _device(DeviceStatus.AVAILABLE)

    (faulted,) = decide_fault(device, FaultDevice(device_id=device.id), now=_NOW)

    assert set(vars(faulted)) == {"device_id", "occurred_at"}


def test_a_transition_does_not_restate_the_address_or_the_label() -> None:
    """A registration is the only event on this stream that carries them,
    so a later reader gets one answer rather than several that could
    disagree."""
    device = _device(DeviceStatus.AVAILABLE)

    (faulted,) = decide_fault(device, FaultDevice(device_id=device.id), now=_NOW)

    assert not hasattr(faulted, "external_ref_scheme")
    assert not hasattr(faulted, "device_name")
    assert DeviceRegistered.__dataclass_fields__.keys() > {"external_ref_scheme", "device_name"}
