"""The decision that registering another address for a dataset produces.

Two invariants, and the second is the one worth the file: an address the
record already holds is refused rather than absorbed, because answering
"done" would hide one store being reported twice under one spelling.
"""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from keeper.custody.aggregates.dataset import (
    CopiedBy,
    Dataset,
    DatasetAddressKnownError,
    DatasetAddressRegistered,
    DatasetNotFoundError,
)
from keeper.custody.features.register_dataset_address import RegisterDatasetAddress, decide
from keeper.shared.identifier import Identifier
from keeper.shared.instant import InvalidOccurredAtError

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 9, 19, 14, 30, tzinfo=UTC)
_BEAMLINE = Identifier(scheme="posix-file", value="/local1/scan_034.h5")
_CENTRAL = Identifier(scheme="gpfs-file", value="/central/raw/scan_034.h5")


def _dataset(*refs: Identifier) -> Dataset:
    return Dataset(
        id=uuid4(), execution_id=uuid4(), step_id=uuid4(), external_refs=refs or (_BEAMLINE,)
    )


def test_an_address_the_dataset_does_not_hold_is_added_beside_the_others() -> None:
    held = _dataset()

    events = decide(
        held,
        RegisterDatasetAddress(dataset_id=held.id, external_ref=_CENTRAL),
        now=_NOW,
    )

    assert events == [
        DatasetAddressRegistered(
            dataset_id=held.id,
            external_ref_scheme="gpfs-file",
            external_ref_value="/central/raw/scan_034.h5",
            copied_by_execution_id=None,
            copied_by_step_id=None,
            occurred_at=_NOW,
        )
    ]


def test_an_address_the_dataset_already_holds_is_refused() -> None:
    """A retry is covered by the idempotency key before reaching here.

    So a caller arriving with an address the record holds is a second
    producer reporting what this system was already told, and
    confirming it would hide one store reported twice.
    """
    held = _dataset()

    with pytest.raises(DatasetAddressKnownError) as refused:
        decide(
            held,
            RegisterDatasetAddress(dataset_id=held.id, external_ref=_BEAMLINE),
            now=_NOW,
        )

    assert refused.value.scheme == "posix-file"


def test_registering_an_address_on_a_dataset_that_was_never_registered_is_refused() -> None:
    missing = uuid4()

    with pytest.raises(DatasetNotFoundError):
        decide(
            None,
            RegisterDatasetAddress(dataset_id=missing, external_ref=_CENTRAL),
            now=_NOW,
        )


def test_a_copy_this_system_dispatched_carries_the_step_that_made_it() -> None:
    held = _dataset()
    by_execution, by_step = uuid4(), uuid4()

    events = decide(
        held,
        RegisterDatasetAddress(
            dataset_id=held.id,
            external_ref=_CENTRAL,
            copied_by=CopiedBy(execution_id=by_execution, step_id=by_step),
        ),
        now=_NOW,
    )

    assert events[0].copied_by_execution_id == by_execution
    assert events[0].copied_by_step_id == by_step


def test_a_copy_nobody_here_dispatched_cites_nothing_rather_than_something_empty() -> None:
    """Absent has to mean absent, which is why this is asserted.

    Most copies are made by facility movement that is not a principal
    here. A citation naming an execution that did not do the copying
    would read as a report this system went and asked for.
    """
    held = _dataset()

    events = decide(
        held,
        RegisterDatasetAddress(dataset_id=held.id, external_ref=_CENTRAL),
        now=_NOW,
    )

    assert events[0].copied_by_execution_id is None
    assert events[0].copied_by_step_id is None


def test_a_reported_time_without_a_timezone_is_refused_before_a_command_exists() -> None:
    with pytest.raises(InvalidOccurredAtError):
        RegisterDatasetAddress(
            dataset_id=uuid4(),
            external_ref=_CENTRAL,
            occurred_at=datetime(2026, 9, 19, 14, 30),
        )
