"""The decision: what registering a description of a dataset produces.

Update-style, so the state comes in already folded and `new_id` is
absent: this command names its stream rather than creating one.

Pure. No awaits, no ports, no clock.
"""

from datetime import datetime

from keeper.custody.aggregates.dataset import (
    Dataset,
    DatasetAddressUnknownError,
    DatasetDescriptionUnchangedError,
    DatasetManifestRegistered,
    DatasetNotFoundError,
)
from keeper.custody.features.register_dataset_manifest.command import RegisterDatasetManifest


def decide(
    state: Dataset | None,
    command: RegisterDatasetManifest,
    *,
    now: datetime,
) -> list[DatasetManifestRegistered]:
    """Decide the events produced by describing a dataset.

    Invariants:
      - State must not be None, or no such dataset was registered
        -> DatasetNotFoundError
      - The copy described must be one this record holds
        -> DatasetAddressUnknownError
      - The description must say something the record does not
        -> DatasetDescriptionUnchangedError

    **A description of an address nobody recorded is refused.** It is
    the same refusal withdrawing one gets, and the same reasoning: a
    caller describing a copy this record has never heard of is working
    from a different idea of where the data is, and telling it so is
    more use than filing a report that connects to nothing. The fold is
    deliberately more tolerant, because a decider is what a caller
    meets and a fold is what a log meets.

    **A description that differs is admitted, however often.** This is
    where the slice parts company with its address sibling, which
    refuses a repeat outright. Looking twice and seeing two things is
    the case worth keeping: a scan engine at some of these beamlines
    reopens a finished file to append the rotation angle of each frame,
    so an early look reports angles that are missing and a later one
    does not, and both are true as of when they were taken.

    What is NOT checked is whether the description is accurate, or
    whether a later one is more accurate than an earlier one. Nothing
    here can reach the data, which is the posture of this whole
    context, so the only thing it can refuse is a statement that
    disagrees with what it already holds.
    """
    if state is None:
        raise DatasetNotFoundError(command.dataset_id)
    if command.external_ref not in state.external_refs:
        raise DatasetAddressUnknownError(
            state.id, command.external_ref.scheme, command.external_ref.value
        )
    held = state.description
    if (
        held is not None
        and held.external_ref == command.external_ref
        and held.manifest == command.manifest
    ):
        raise DatasetDescriptionUnchangedError(
            state.id, command.external_ref.scheme, command.external_ref.value
        )
    return [
        DatasetManifestRegistered(
            dataset_id=command.dataset_id,
            external_ref_scheme=command.external_ref.scheme,
            external_ref_value=command.external_ref.value,
            convention=command.manifest.convention,
            entries=command.manifest.entries,
            occurred_at=now,
        )
    ]


__all__ = ["decide"]
