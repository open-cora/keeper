"""The intent: tell this system that an address stopped answering."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from keeper.shared.identifier import Identifier
from keeper.shared.instant import normalize_occurred_at


@dataclass(frozen=True)
class WithdrawDatasetAddress:
    """Record that this data is no longer reachable at this address.

    Withdraw rather than delete, and the distinction is whose act it
    was. This system removed nothing and could not. Something purged a
    disk, expired a retention window, unmounted an export or reorganised
    a store, and this is the hearing, which is the posture the genesis
    command takes toward data being written.

    The address and not the dataset. The record stays, the run that
    produced the data stays named, and what goes is one place it could
    be read. A dataset that loses its last address is a dataset whose
    data is gone, which this context can say and a deleted row could
    not.

    No citation, where the sibling has one. A purge is housekeeping no
    execution is dispatched to perform, so a field for the work that did
    it would be empty on every row anybody could write today.

    `occurred_at` is when the address stopped answering, as the caller
    reports it, and a caller who omits it gets the moment the report
    arrived. Accepted for the reason R8 attaches it to: it happened
    somewhere this system was not.
    """

    dataset_id: UUID
    external_ref: Identifier
    occurred_at: datetime | None = None

    def __post_init__(self) -> None:
        """Refuse a naive timestamp and store the UTC form of an aware one.

        Frozen, so the normalised value goes back through
        `object.__setattr__`, the way the shared identifier does it.
        """
        if self.occurred_at is not None:
            object.__setattr__(self, "occurred_at", normalize_occurred_at(self.occurred_at))


__all__ = ["WithdrawDatasetAddress"]
