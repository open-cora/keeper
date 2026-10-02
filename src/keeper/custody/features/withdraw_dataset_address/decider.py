"""The decision: what withdrawing an address from a dataset produces.

Update-style, so the state comes in already folded and `new_id` is
absent: this command names its stream rather than creating one.

Pure. No awaits, no ports, no clock.
"""

from datetime import datetime

from keeper.custody.aggregates.dataset import (
    Dataset,
    DatasetAddressUnknownError,
    DatasetAddressWithdrawn,
    DatasetNotFoundError,
)
from keeper.custody.features.withdraw_dataset_address.command import WithdrawDatasetAddress


def decide(
    state: Dataset | None,
    command: WithdrawDatasetAddress,
    *,
    now: datetime,
) -> list[DatasetAddressWithdrawn]:
    """Decide the events produced by withdrawing an address.

    Invariants:
      - State must not be None, or no such dataset was registered
        -> DatasetNotFoundError
      - The address must be one this dataset holds
        -> DatasetAddressUnknownError

    **An address nobody recorded is refused rather than confirmed.** A
    caller withdrawing one is working from a different idea of where the
    data is than this record holds, and saying "done" would let the two
    stay apart quietly. The fold tolerates the same row, because a log
    and a caller are met by different things, and that difference is
    stated where the fold is.

    Withdrawing the last address is allowed. A dataset with none is not
    a broken record: it says this system knew where data was, every copy
    it knew of is gone, and the run that produced it is still named.
    """
    if state is None:
        raise DatasetNotFoundError(command.dataset_id)
    if command.external_ref not in state.external_refs:
        raise DatasetAddressUnknownError(
            state.id, command.external_ref.scheme, command.external_ref.value
        )
    return [
        DatasetAddressWithdrawn(
            dataset_id=command.dataset_id,
            external_ref_scheme=command.external_ref.scheme,
            external_ref_value=command.external_ref.value,
            occurred_at=now,
        )
    ]


__all__ = ["decide"]
