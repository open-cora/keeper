"""The decision that describing a dataset produces.

Three invariants, and one deliberate non-refusal that is the point of
the slice: a dataset may be described again and again, so long as each
description says something the record does not already say.
"""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from keeper.custody.aggregates.dataset import (
    Dataset,
    DatasetAddressUnknownError,
    DatasetDescriptionUnchangedError,
    DatasetManifestRegistered,
    DatasetNotFoundError,
    Description,
    Entry,
    Extent,
    Manifest,
)
from keeper.custody.features.register_dataset_manifest import RegisterDatasetManifest, decide
from keeper.shared.identifier import Identifier
from keeper.shared.instant import InvalidOccurredAtError

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 9, 19, 14, 30, tzinfo=UTC)
_EARLIER = datetime(2026, 9, 19, 14, 0, tzinfo=UTC)
_BEAMLINE = Identifier(scheme="posix-file", value="/local1/scan_034.h5")
_CENTRAL = Identifier(scheme="gpfs-file", value="/central/raw/scan_034.h5")

_PROJECTIONS = Entry(
    path="/exchange/data",
    extent=Extent(shape=(1800, 2048, 2048), capacity=None, dtype="uint16"),
    role="projections",
)
_ANGLES = Entry(
    path="/exchange/theta",
    extent=Extent(shape=(1800,), capacity=None, dtype="float64"),
    role="projection-angles",
)


def _manifest(*entries: Entry) -> Manifest:
    return Manifest(convention="dxchange", entries=entries or (_PROJECTIONS,))


def _dataset(*, described: Description | None = None, refs: tuple[Identifier, ...] = ()) -> Dataset:
    return Dataset(
        id=uuid4(),
        execution_id=uuid4(),
        step_id=uuid4(),
        external_refs=refs or (_BEAMLINE,),
        description=described,
        findings=(),
    )


def _command(
    held: Dataset, manifest: Manifest, ref: Identifier = _BEAMLINE
) -> RegisterDatasetManifest:
    return RegisterDatasetManifest(dataset_id=held.id, external_ref=ref, manifest=manifest)


def test_describing_a_dataset_nobody_has_described_emits_one_event() -> None:
    held = _dataset()

    events = decide(held, _command(held, _manifest()), now=_NOW)

    assert events == [
        DatasetManifestRegistered(
            dataset_id=held.id,
            external_ref_scheme=_BEAMLINE.scheme,
            external_ref_value=_BEAMLINE.value,
            convention="dxchange",
            entries=(_PROJECTIONS,),
            occurred_at=_NOW,
        )
    ]


def test_describing_a_dataset_that_was_never_registered_is_refused() -> None:
    with pytest.raises(DatasetNotFoundError):
        decide(
            None,
            RegisterDatasetManifest(
                dataset_id=uuid4(), external_ref=_BEAMLINE, manifest=_manifest()
            ),
            now=_NOW,
        )


def test_describing_a_copy_the_record_does_not_hold_is_refused() -> None:
    held = _dataset(refs=(_BEAMLINE,))

    with pytest.raises(DatasetAddressUnknownError):
        decide(held, _command(held, _manifest(), ref=_CENTRAL), now=_NOW)


def test_a_second_look_that_found_something_new_is_recorded_beside_the_first() -> None:
    """The failure this slice exists for, as the case it must not refuse.

    An early look reports frames with no angles beside them and a later
    one reports the angles a scan engine appended after closing the
    file. Both are true as of when they were taken.
    """
    held = _dataset(
        described=Description(
            manifest=_manifest(_PROJECTIONS),
            external_ref=_BEAMLINE,
            described_at=_EARLIER,
        )
    )

    events = decide(held, _command(held, _manifest(_PROJECTIONS, _ANGLES)), now=_NOW)

    assert len(events) == 1
    assert events[0].entries == (_PROJECTIONS, _ANGLES)


def test_a_description_repeating_what_the_record_already_says_is_refused() -> None:
    held = _dataset(
        described=Description(
            manifest=_manifest(_PROJECTIONS),
            external_ref=_BEAMLINE,
            described_at=_EARLIER,
        )
    )

    with pytest.raises(DatasetDescriptionUnchangedError):
        decide(held, _command(held, _manifest(_PROJECTIONS)), now=_NOW)


def test_the_same_description_of_a_different_copy_is_not_a_repeat() -> None:
    """Two copies described alike is two observations, not one retried.

    The refusal above is aimed at a redelivered report, which names the
    copy its sender opened. A caller naming a different copy opened a
    different container and found the same thing in it, which is worth
    recording and is how a reader learns the two agree.
    """
    held = _dataset(
        refs=(_BEAMLINE, _CENTRAL),
        described=Description(
            manifest=_manifest(_PROJECTIONS),
            external_ref=_BEAMLINE,
            described_at=_EARLIER,
        ),
    )

    events = decide(held, _command(held, _manifest(_PROJECTIONS), ref=_CENTRAL), now=_NOW)

    assert events[0].external_ref_value == _CENTRAL.value


def test_a_description_that_found_nothing_worth_naming_is_recorded() -> None:
    """Empty entries and no description at all are different answers.

    A reader that understood the container and found nothing in it says
    so by sending an empty manifest. A reader that did not understand
    the container sends nothing, and the record stays undescribed.
    """
    held = _dataset()

    events = decide(held, _command(held, Manifest(convention="unknown", entries=())), now=_NOW)

    assert events[0].entries == ()


def test_a_reported_time_without_a_timezone_is_refused_before_a_command_exists() -> None:
    with pytest.raises(InvalidOccurredAtError):
        RegisterDatasetManifest(
            dataset_id=uuid4(),
            external_ref=_BEAMLINE,
            manifest=_manifest(),
            occurred_at=datetime(2026, 9, 19, 14, 30),
        )
