"""The Device aggregate: state, events, evolver, and its two read paths."""

from keeper.equipment.aggregates.device.events import (
    DeviceEvent,
    DeviceFaulted,
    DeviceRecovered,
    DeviceRegistered,
    DeviceRetired,
    from_stored,
    to_payload,
)
from keeper.equipment.aggregates.device.evolver import evolve, fold
from keeper.equipment.aggregates.device.read import (
    DEVICE_STREAM_TYPE,
    load_device,
    load_device_with_version,
)
from keeper.equipment.aggregates.device.state import (
    DEVICE_NAME_MAX_LENGTH,
    Device,
    DeviceAlreadyExistsError,
    DeviceCannotBeFaultedError,
    DeviceCannotBeRecoveredError,
    DeviceCannotBeRetiredError,
    DeviceName,
    DeviceNotFoundError,
    DeviceStatus,
    InvalidDeviceFilterError,
    InvalidDeviceNameError,
)
from keeper.equipment.aggregates.device.summary import (
    DeviceSummary,
    DeviceSummaryLookup,
    DeviceSummaryPage,
)

__all__ = [
    "DEVICE_NAME_MAX_LENGTH",
    "DEVICE_STREAM_TYPE",
    "Device",
    "DeviceAlreadyExistsError",
    "DeviceCannotBeFaultedError",
    "DeviceCannotBeRecoveredError",
    "DeviceCannotBeRetiredError",
    "DeviceEvent",
    "DeviceFaulted",
    "DeviceName",
    "DeviceNotFoundError",
    "DeviceRecovered",
    "DeviceRegistered",
    "DeviceRetired",
    "DeviceStatus",
    "DeviceSummary",
    "DeviceSummaryLookup",
    "DeviceSummaryPage",
    "InvalidDeviceFilterError",
    "InvalidDeviceNameError",
    "evolve",
    "fold",
    "from_stored",
    "load_device",
    "load_device_with_version",
    "to_payload",
]
