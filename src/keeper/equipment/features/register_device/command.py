"""The intent: enrol a piece of hardware in this system's record."""

from dataclasses import dataclass

from keeper.equipment.aggregates.device import DeviceName
from keeper.shared.identifier import Identifier


@dataclass(frozen=True)
class RegisterDevice:
    """Enrol the hardware at this address, under this label.

    Register, not define and not install. This system did not put
    anything at a beamline and could not; the hardware is there whether
    or not anything here has heard of it, and this command is the
    hearing. The glossary's genesis test is the check: "register a
    device" sounds like enrolling something that came from elsewhere,
    and "define a device" sounds like inventing hardware.

    `external_ref` arrives as the value object rather than as two loose
    strings, so a caller cannot hand over half a reference. It is the
    only handle that means anything outside this system: a control
    library's name for a device is assigned in whatever process
    constructed it, so two profiles name one motor differently and
    nothing records that they are the same.

    `name` is this system's own label, and the caller supplies it
    because nothing else can. It is NOT the facility's description
    field. Copying that in is the one thing an adapter must not do:
    it is free text somebody typed at a beamline, and free text swept in
    from outside is how a person's name reaches a table that cannot be
    edited.

    **There is no `occurred_at`, and the absence is the point.** The
    sibling `register_dataset` takes one, because data was written
    somewhere at a knowable moment and a backfill out of an archive
    would otherwise date every dataset to the afternoon of the import.
    Enrolling a device has no such moment. When the hardware was
    installed is not something any adapter can supply, and the only act
    this system can date is its own enrolling, so the moment it writes
    one is the moment it happened. That is R8 landing on the makes side,
    beside `register_actor`.

    The device id and the correlation id are not the caller's. They come
    from the handler's ports, so the decision this command produces is
    reproducible on replay.
    """

    external_ref: Identifier
    name: DeviceName


__all__ = ["RegisterDevice"]
