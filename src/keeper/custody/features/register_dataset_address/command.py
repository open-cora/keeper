"""The intent: tell this system about another place the data answers to."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from keeper.custody.aggregates.dataset import CopiedBy
from keeper.shared.identifier import Identifier
from keeper.shared.instant import normalize_occurred_at


@dataclass(frozen=True)
class RegisterDatasetAddress:
    """Register that this data is also reachable at this address.

    Register, for the reason the genesis command is a registration: this
    system did not put the data there and could not. Something else
    moved or published it, and this enrols the result. The imperative is
    shorthand for "write down that this happened", which is the right
    column of R8 in docs/reference/naming.md. A surface that asks
    something to go and make a copy is a different command with a
    different name, and does not exist.

    An address rather than a copy, because the two come apart. The same
    bytes answer to a local path, an NFS path and a server URI at once,
    and counting copies would need this system to know when two paths
    are one file. What a reader of this record wants is which address it
    can reach from where it is standing.

    `external_ref` arrives as the value object rather than as two loose
    strings, so a caller cannot hand over half a reference, which is the
    same reason the genesis command takes one.

    `copied_by` is the work that made the copy, when this system is the
    one that asked for it, and absent otherwise. It travels as one
    object for the reason the reference does: half a citation is not a
    thing a caller should be able to express.

    `occurred_at` is when the copy landed, as the caller reports it, and
    a caller who omits it gets the moment the report arrived. Accepted
    because the copy happened somewhere this system was not, which is
    the condition R8 attaches it to.
    """

    dataset_id: UUID
    external_ref: Identifier
    copied_by: CopiedBy | None = None
    occurred_at: datetime | None = None

    def __post_init__(self) -> None:
        """Refuse a naive timestamp and store the UTC form of an aware one.

        Frozen, so the normalised value goes back through
        `object.__setattr__`, the way the shared identifier does it.
        """
        if self.occurred_at is not None:
            object.__setattr__(self, "occurred_at", normalize_occurred_at(self.occurred_at))


__all__ = ["RegisterDatasetAddress"]
