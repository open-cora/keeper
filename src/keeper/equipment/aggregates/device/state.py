"""Device state and its domain errors.

A Device is one piece of hardware this system holds a record of, and
what state it was last reported in.

## What identifies it, and why it is not the name

`external_ref` is the handle, and it is the only thing here two
independent clients will agree on. A control library's name for a device
is a constructor argument, so it survives exactly as long as the process
that chose it: two startup profiles can build one motor under two names,
both connected at once, with nothing anywhere recording that they are one
device.

The facility-side label is no better. It is free text, writable by any
client, and under no obligation to be filled in at all.

So the reference is the address the control system publishes the device
at, as the same open-scheme pair a run and a dataset carry. What a
scheme means is the deployment's fact, not this system's.

## What `name` is, and the one rule on it

This system's own label, authored here, so it is a fact the record makes
rather than one it reports and cannot be wrong about the world. It
exists because a register that lists addresses and nothing else is not
usable by a person.

**An adapter must not copy the facility's own description field into
it.** That field is free text somebody typed at a beamline, and free
text swept in from outside is where a person's name arrives in a table
that cannot be edited. The same rule, for the same reason, keeps a
reason off a run.

## What `beamline` and `group` are

Two more authored labels, the same kind of thing as `name` and subject to
the same rule against copying a facility field into them.

`beamline` is where the device is, written the way the descriptor
directory writes it. It is stored as given and compared as given, which
is what Execution already does with a procedure's beamline, and for the
same reason: a second register of which beamlines exist would be a thing
to keep in step with the descriptors for nobody's benefit.

`group` is which functional cluster a device belongs to at that
beamline, and it is optional because most records honestly belong to
none. A motor whose only description is the channel it occupies in a
crate is not part of anything anybody has named, and inventing a group
for it would manufacture a fact.

**`group` is a value rows share, not a thing that owns them.** There is
no group aggregate, no parent, and no membership anywhere else. A group
exists while some device says that word and stops existing when the last
one stops. What that refuses is a catalog: no nesting, no ordering, and
nothing that can be said about a group rather than about a device.

The pair is meant together. A group name means different hardware at
each beamline, so a group without a beamline beside it does not pick out
a set.

## The status, and where it comes from

Derived in the fold from which events the stream carries, never stored,
which is the only way to keep the two from disagreeing. Three values:

    Available   registered, and nothing stands against it
    Faulted     a fault was reported and nothing has recovered it
    Retired     this system no longer counts this device

The three split by voice, and the split is the whole shape of this
aggregate. Available and Retired are this system's own bookkeeping.
Faulted is the only one that is a claim about the world.

**Available does not mean the device works.** It means no fault has been
reported and none stands. That is the same caveat a run's Running
carries, and here it is weaker still, for three reasons. A fault is
at-most-once, delivered only to whoever was subscribed when it happened.
A reporter's cached view of an alarm outlives the device it describes, so
the value path fails loudly while the alarm path fails silently. And
hardware outlives the thing driving it, with no ending emitted on any
path.

## What a fault is, and what is not stored

A fault is the reporter's judgement. What a control system publishes is
an alarm severity, and an alarm is not a fault: the routine ones are
routine, and a device in one is usually still usable. Deciding that a
given severity amounts to a fault is the same call a reporter already
makes when it picks one of a run's three terminals.

So the severity does not reach the record. On the record it would invite
a later reader to derive faultedness from it, and that is a claim about
hardware health this system never made.

## What this aggregate does not hold

Readings, of any kind. A single device publishes tens of signals that
move continuously, and an append-only log is the wrong home for them.
Nor the device's configuration: a station's configuration routinely
carries a named person, one call away, which makes the easy
implementation the dangerous one.

Nor an interval. "Was this device faulted while that run was going" is
not answerable here and the absence is deliberate. Faults are point
events. Deriving a span from two of them reads as precision while
resting on a clear nobody may have seen, and one missed clear extends
the span forever.

Nor a tree. Where one device stops is a client-side composition, so what
is registered is the thing the address names.
"""

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from keeper.shared.bounded_text import bounded_name
from keeper.shared.identifier import Identifier

DEVICE_NAME_MAX_LENGTH = 100
"""Longest label this system will hold for a device.

Generous next to the description fields a control system publishes, and
bounded because every text field in this tree is. A label that wants
more than this is prose, and prose about hardware belongs wherever the
facility keeps its documentation.
"""


class InvalidDeviceNameError(ValueError):
    """A device label is empty, whitespace-only, or too long."""

    def __init__(self, value: str) -> None:
        super().__init__(f"Device name is invalid (got: {value!r})")
        self.value = value


@bounded_name(max_length=DEVICE_NAME_MAX_LENGTH, error_class=InvalidDeviceNameError)
@dataclass(frozen=True)
class DeviceName:
    """The label this system holds for a device, trimmed and bounded."""

    value: str


DEVICE_BEAMLINE_MAX_LENGTH = 100
"""Longest beamline name this system will hold on a device.

The same bound Execution puts on a procedure's beamline, because they
name the same thing and a device that could not be registered at a
beamline a procedure can be dispatched to would be a trap.
"""


class InvalidDeviceBeamlineError(ValueError):
    """A device beamline is empty, whitespace-only, or too long."""

    def __init__(self, value: str) -> None:
        super().__init__(f"Device beamline is invalid (got: {value!r})")
        self.value = value


@bounded_name(max_length=DEVICE_BEAMLINE_MAX_LENGTH, error_class=InvalidDeviceBeamlineError)
@dataclass(frozen=True)
class DeviceBeamline:
    """Where a device is, as the descriptor directory writes it."""

    value: str


DEVICE_GROUP_MAX_LENGTH = 100
"""Longest group name this system will hold on a device.

Matched to the label beside it rather than argued separately. A group
name is a short phrase people say out loud, so the bound is not the
thing that will ever be reached.
"""


class InvalidDeviceGroupError(ValueError):
    """A device group is empty, whitespace-only, or too long.

    Absent is the way to say a device belongs to no group. A present but
    blank one is a caller who meant something and did not say it, which
    is the case this refuses.
    """

    def __init__(self, value: str) -> None:
        super().__init__(f"Device group is invalid (got: {value!r})")
        self.value = value


@bounded_name(max_length=DEVICE_GROUP_MAX_LENGTH, error_class=InvalidDeviceGroupError)
@dataclass(frozen=True)
class DeviceGroup:
    """Which functional cluster a device belongs to, at its own beamline."""

    value: str


class DeviceStatus(StrEnum):
    """What this system has been told about a device.

    Values are PascalCase strings so a log line or a response body reads
    without a mapping step, which is the spelling a run's status uses.

    Nothing here says the device is well NOW. `AVAILABLE` says the
    stream has a genesis event, no fault standing over it, and no
    retirement. See the module docstring for the three separate reasons
    that is a weaker claim than it looks.
    """

    AVAILABLE = "Available"
    FAULTED = "Faulted"
    RETIRED = "Retired"

    @property
    def is_terminal(self) -> bool:
        """Whether nothing further can be recorded against the device.

        One value, and it is asked rather than compared against a
        literal in three deciders, which is the shape a run's terminal
        set already takes. A second terminal would be a change here
        rather than in each of them.
        """
        return self is DeviceStatus.RETIRED


class InvalidDeviceFilterError(ValueError):
    """A list was asked for half of an external reference.

    An external reference is a scheme and a value together, and either
    one alone names nothing: a value without its scheme could belong to
    any control system's vocabulary, and a scheme without a value is a
    vocabulary with no word in it.

    Refused rather than ignored. Dropping the half that arrived would
    answer a question nobody asked, with every device in the deployment,
    and a reporter looking for the one at an address would get a page
    and fault whichever came first.
    """

    def __init__(self, scheme: str | None, value: str | None) -> None:
        missing = "value" if scheme is not None else "scheme"
        super().__init__(
            f"An external reference filter needs both halves; the {missing} is missing"
        )
        self.scheme = scheme
        self.value = value


class DeviceNotFoundError(Exception):
    """A query named a device id with no stream behind it."""

    def __init__(self, device_id: UUID) -> None:
        super().__init__(f"Device {device_id} not found")
        self.device_id = device_id


class DeviceAlreadyExistsError(Exception):
    """Registration was attempted against an id that already has a stream.

    Unreachable through the ordinary path, because a registering handler
    mints a fresh id and a fresh id has no history. It exists so the
    decider states the precondition it relies on rather than assuming
    it, and so a caller supplying its own id is refused instead of
    writing a second genesis event onto a live stream.
    """

    def __init__(self, device_id: UUID) -> None:
        super().__init__(f"Device {device_id} already exists")
        self.device_id = device_id


class DeviceCannotBeFaultedError(Exception):
    """A fault was reported for a device that cannot take one.

    Refused from `FAULTED`, where a second report with no recovery
    between them says nothing the stream does not already say, and from
    `RETIRED`, where this system has stopped counting the device.

    Same shape as its two siblings, and per R6 in
    docs/reference/naming.md for the same reason: the verb in the class
    name is the diagnostic, and the status it carries is the fact the
    caller does not have.
    """

    def __init__(self, device_id: UUID, status: DeviceStatus) -> None:
        super().__init__(f"Device {device_id} cannot be faulted: it is already {status}")
        self.device_id = device_id
        self.status = status


class DeviceCannotBeRecoveredError(Exception):
    """A recovery was reported for a device that is not faulted.

    The mirror of `DeviceCannotBeFaultedError`. Refused from
    `AVAILABLE`, where there is no fault to come back from, and from
    `RETIRED`.

    The two are not equally likely, and the status on the refusal is
    what lets a caller tell the cases apart. A duplicate fault is
    usually a redelivery. A recovery against an available device usually
    means the reporter missed the fault, which is the ordinary failure
    rather than the exotic one, because a fault is delivered only to
    whoever was subscribed at the time.
    """

    def __init__(self, device_id: UUID, status: DeviceStatus) -> None:
        super().__init__(f"Device {device_id} cannot be recovered: it is already {status}")
        self.device_id = device_id
        self.status = status


class DeviceCannotBeRetiredError(Exception):
    """Retirement was asked for a device already retired.

    Refused only from `RETIRED`. A faulted device can be retired, and
    that is the ordinary way a broken thing leaves the register rather
    than an edge case: nothing requires it to be recovered first.
    """

    def __init__(self, device_id: UUID, status: DeviceStatus) -> None:
        super().__init__(f"Device {device_id} cannot be retired: it is already {status}")
        self.device_id = device_id
        self.status = status


@dataclass(frozen=True)
class Device:
    """One piece of hardware, as the fold leaves it.

    `external_ref` is where the control system publishes it, as an
    open-scheme pair. The scheme names the addressing vocabulary and is
    not a closed set here, because which control system a deployment
    runs is a deployment's fact.

    `status` is the only field the fold computes rather than copies. See
    the module docstring for why it is derived from the event type and
    not read off a payload.
    """

    id: UUID
    external_ref: Identifier
    name: DeviceName
    beamline: DeviceBeamline
    group: DeviceGroup | None
    status: DeviceStatus

    @property
    def is_retired(self) -> bool:
        """Whether this system has stopped counting the device.

        Asked by all three transition deciders, so the terminal set is
        written once, on the status, rather than three times.
        """
        return self.status.is_terminal


__all__ = [
    "DEVICE_BEAMLINE_MAX_LENGTH",
    "DEVICE_GROUP_MAX_LENGTH",
    "DEVICE_NAME_MAX_LENGTH",
    "Device",
    "DeviceAlreadyExistsError",
    "DeviceBeamline",
    "DeviceCannotBeFaultedError",
    "DeviceCannotBeRecoveredError",
    "DeviceCannotBeRetiredError",
    "DeviceGroup",
    "DeviceName",
    "DeviceNotFoundError",
    "DeviceStatus",
    "InvalidDeviceBeamlineError",
    "InvalidDeviceFilterError",
    "InvalidDeviceGroupError",
    "InvalidDeviceNameError",
]
