"""The intent: tell this system what somebody found inside the data."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from keeper.custody.aggregates.dataset.manifest import Manifest
from keeper.shared.identifier import Identifier
from keeper.shared.instant import normalize_occurred_at


@dataclass(frozen=True)
class RegisterDatasetManifest:
    """Register what a reader found inside one copy of this data.

    Register, for the reason every other command on this aggregate is a
    registration: this system did not open anything and could not. A
    program standing beside the data did, and this writes down what it
    reported. R8 in docs/reference/naming.md puts that in the describes
    column rather than the makes column, which is also why a caller may
    supply the moment.

    `external_ref` is the copy that was opened, and it is required. A
    dataset is commonly at several addresses at once, so a report
    naming none of them could not be told apart from a report about a
    different copy. It arrives as the value object for the reason the
    sibling's does: a caller should not be able to hand over half a
    reference.

    `manifest` arrives whole for the same reason. A convention with no
    entries beside it, or entries with no convention, is half a
    statement, and the vocabulary that makes the entries readable is
    the convention naming it.

    `occurred_at` is when the container was read, as the caller reports
    it, and a caller who omits it gets the moment the report arrived.
    It matters more here than on the sibling commands: a description is
    a statement about a moment and the moment is how a later reader
    tells an early look from a later one.
    """

    dataset_id: UUID
    external_ref: Identifier
    manifest: Manifest
    occurred_at: datetime | None = None

    def __post_init__(self) -> None:
        """Refuse a naive timestamp and store the UTC form of an aware one.

        Frozen, so the normalised value goes back through
        `object.__setattr__`, the way the shared identifier does it.
        """
        if self.occurred_at is not None:
            object.__setattr__(self, "occurred_at", normalize_occurred_at(self.occurred_at))


__all__ = ["RegisterDatasetManifest"]
