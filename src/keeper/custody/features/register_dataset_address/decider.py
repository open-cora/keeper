"""The decision: what registering another address for a dataset produces.

Update-style, so the state comes in already folded and `new_id` is
absent: this command names its stream rather than creating one.

Pure. No awaits, no ports, no clock.
"""

from datetime import datetime

from keeper.custody.aggregates.dataset import (
    Dataset,
    DatasetAddressKnownError,
    DatasetAddressRegistered,
    DatasetNotFoundError,
)
from keeper.custody.features.register_dataset_address.command import RegisterDatasetAddress


def decide(
    state: Dataset | None,
    command: RegisterDatasetAddress,
    *,
    now: datetime,
) -> list[DatasetAddressRegistered]:
    """Decide the events produced by registering another address.

    Invariants:
      - State must not be None, or no such dataset was registered
        -> DatasetNotFoundError
      - The address must not already be held
        -> DatasetAddressKnownError

    **A duplicate address is refused rather than absorbed.** A producer
    retrying one report is covered before this by the idempotency key,
    which acts on what it sent, so a caller arriving here with an
    address the record already holds is a second producer reporting
    something this system was already told. Answering "done" would hide
    one store being reported twice under one spelling, which is the
    failure the genesis event's own notes call out as real rather than
    hypothetical.

    What is NOT checked is whether the address resolves, or whether the
    data at it is the same data. Nothing here can reach a store, which
    is the whole posture of this context, so the only thing it can
    refuse is a statement that disagrees with what it already holds.
    """
    if state is None:
        raise DatasetNotFoundError(command.dataset_id)
    if command.external_ref in state.external_refs:
        raise DatasetAddressKnownError(
            state.id, command.external_ref.scheme, command.external_ref.value
        )
    copied_by = command.copied_by
    return [
        DatasetAddressRegistered(
            dataset_id=command.dataset_id,
            external_ref_scheme=command.external_ref.scheme,
            external_ref_value=command.external_ref.value,
            copied_by_execution_id=None if copied_by is None else copied_by.execution_id,
            copied_by_step_id=None if copied_by is None else copied_by.step_id,
            occurred_at=now,
        )
    ]


__all__ = ["decide"]
