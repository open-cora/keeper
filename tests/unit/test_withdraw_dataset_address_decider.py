"""The decision that withdrawing an address from a dataset produces.

Two invariants, and one deliberate non-refusal: a dataset may lose its
last address, because a record of a run whose data is gone is a more
useful thing to hold than no record at all.
"""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from keeper.custody.aggregates.dataset import (
    Dataset,
    DatasetAddressUnknownError,
    DatasetAddressWithdrawn,
    DatasetNotFoundError,
)
from keeper.custody.features.withdraw_dataset_address import WithdrawDatasetAddress, decide
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


def test_withdrawing_an_address_the_dataset_holds_emits_one_event() -> None:
    held = _dataset(_BEAMLINE, _CENTRAL)

    events = decide(
        held,
        WithdrawDatasetAddress(dataset_id=held.id, external_ref=_BEAMLINE),
        now=_NOW,
    )

    assert events == [
        DatasetAddressWithdrawn(
            dataset_id=held.id,
            external_ref_scheme="posix-file",
            external_ref_value="/local1/scan_034.h5",
            occurred_at=_NOW,
        )
    ]


def test_withdrawing_an_address_the_dataset_does_not_hold_is_refused() -> None:
    """Refused rather than confirmed as already done.

    A caller withdrawing an address nobody recorded is working from a
    different idea of where the data is than this record holds, and
    saying "done" would let the two stay apart quietly.
    """
    held = _dataset(_BEAMLINE)

    with pytest.raises(DatasetAddressUnknownError) as refused:
        decide(
            held,
            WithdrawDatasetAddress(dataset_id=held.id, external_ref=_CENTRAL),
            now=_NOW,
        )

    assert refused.value.scheme == "gpfs-file"


def test_withdrawing_from_a_dataset_that_was_never_registered_is_refused() -> None:
    with pytest.raises(DatasetNotFoundError):
        decide(
            None,
            WithdrawDatasetAddress(dataset_id=uuid4(), external_ref=_CENTRAL),
            now=_NOW,
        )


def test_the_last_address_may_be_withdrawn_leaving_a_run_whose_data_is_gone() -> None:
    """Allowed on purpose, and the reason is what this context is for.

    A dataset with no addresses says this system knew where data was,
    every copy it knew of is gone, and the run that produced it is
    still named. Refusing would force a caller to either lie or delete,
    and a deleted row answers "what did this run produce" with silence.
    """
    held = _dataset(_BEAMLINE)

    events = decide(
        held,
        WithdrawDatasetAddress(dataset_id=held.id, external_ref=_BEAMLINE),
        now=_NOW,
    )

    assert len(events) == 1


def test_a_reported_time_without_a_timezone_is_refused_before_a_command_exists() -> None:
    with pytest.raises(InvalidOccurredAtError):
        WithdrawDatasetAddress(
            dataset_id=uuid4(),
            external_ref=_CENTRAL,
            occurred_at=datetime(2026, 9, 19, 14, 30),
        )
