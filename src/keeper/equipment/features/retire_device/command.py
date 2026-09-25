"""The intent: stop counting this device."""

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class RetireDevice:
    """Stop counting this device.

    Retire, not withdraw and not remove. Withdraw is spoken for: a
    proposal is what gets withdrawn in this tree, by the party that made
    it, and the glossary defines each term once. Remove would claim the
    hardware left the beamline, which is a different fact at a different
    moment that this system was not present for.

    What this records is that this system's register no longer carries
    the device. That fact is made by the record rather than described by
    it.

    **There is no `occurred_at`**, and that is R8 running between two
    commands on one stream. A fault happened out there and its command
    takes a time. Retiring happens here, so the moment this system
    writes one is the moment it happened, and a supplied time would be
    fiction.

    A faulted device can be retired without being recovered first. That
    is the ordinary way a broken thing leaves a register, not an edge
    case.
    """

    device_id: UUID


__all__ = ["RetireDevice"]
