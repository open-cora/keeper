"""What a description may hold, and that it survives the trip to a row.

The load-bearing test here is the first one. Every other rule in this
file is a bound somebody could argue about; that one is the whole
reason a description is allowed into this record at all, and it is
written as a field-set assertion so that widening the shape is an act
somebody has to come and defend rather than a field that slips in.
"""

import dataclasses
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from keeper.custody.aggregates.dataset import (
    MANIFEST_MAX_ENTRIES,
    DatasetManifestRegistered,
    DatasetRegistered,
    Entry,
    Extent,
    InvalidManifestError,
    Manifest,
    fold,
    from_stored,
    to_payload,
)
from keeper.infrastructure.ports.event_store import StoredEvent
from keeper.shared.identifier import Identifier

pytestmark = pytest.mark.unit

_WHEN = datetime(2026, 9, 19, 14, 30, tzinfo=UTC)
_LATER = datetime(2026, 9, 19, 15, 0, tzinfo=UTC)
_SCHEME = "posix-file"
_VALUE = "/local1/scan_034.h5"


def test_a_description_has_no_field_that_could_hold_a_value_read_from_the_data() -> None:
    """A description says whether to open the data, never what it says.

    There is nowhere here to park a mean, a sigma or a signal-to-noise
    ratio, and that is what makes this an index rather than a cache of
    the container. A fourth field on either shape fails this, which is
    the intended cost: the argument for it gets made here, in the open,
    and not in a payload that is append-only once it ships.
    """
    assert [f.name for f in dataclasses.fields(Entry)] == ["path", "extent", "role"]
    assert [f.name for f in dataclasses.fields(Extent)] == ["shape", "capacity", "dtype"]


def test_a_container_counted_by_two_numbers_is_refused() -> None:
    with pytest.raises(InvalidManifestError):
        Extent(shape=(4, 2), capacity=None, dtype=None)


def test_an_array_keeps_every_dimension_because_it_declared_an_element_type() -> None:
    assert Extent(shape=(1800, 2048, 2048), capacity=None, dtype="uint16").shape == (
        1800,
        2048,
        2048,
    )


def test_a_shape_counting_backwards_is_refused() -> None:
    with pytest.raises(InvalidManifestError):
        Extent(shape=(-1,), capacity=None, dtype=None)


def test_a_capacity_of_a_different_rank_than_its_shape_is_refused() -> None:
    with pytest.raises(InvalidManifestError):
        Extent(shape=(1, 2, 2), capacity=(100,), dtype="uint16")


def test_a_word_given_as_an_empty_string_is_refused_so_absence_has_one_spelling() -> None:
    """Two spellings of nobody-knows would make the vocabulary uncountable."""
    with pytest.raises(InvalidManifestError):
        Entry(path="/exchange/data", extent=None, role="  ")
    with pytest.raises(InvalidManifestError):
        Extent(shape=(1,), capacity=None, dtype="")


def test_an_entry_with_no_role_is_held_because_unnamed_is_not_unreal() -> None:
    assert Entry(path="/measurement/ancillary", extent=None, role=None).role is None


def test_a_path_long_enough_to_be_a_payload_is_refused() -> None:
    with pytest.raises(InvalidManifestError):
        Entry(path="/" + "x" * 600, extent=None, role=None)


def test_a_blank_path_is_refused_because_an_entry_names_where_it_is() -> None:
    with pytest.raises(InvalidManifestError):
        Entry(path="   ", extent=None, role=None)


def test_a_manifest_with_no_convention_is_refused_because_unknown_is_the_honest_word() -> None:
    with pytest.raises(InvalidManifestError):
        Manifest(convention=" ", entries=())


def test_a_container_too_wide_to_describe_is_refused_rather_than_trimmed() -> None:
    """Keeping the first sixty-four would look complete and would not be."""
    too_many = tuple(
        Entry(path=f"/exchange/data_{index}", extent=None, role=None)
        for index in range(MANIFEST_MAX_ENTRIES + 1)
    )

    with pytest.raises(InvalidManifestError):
        Manifest(convention="dxchange", entries=too_many)


def _registered() -> DatasetRegistered:
    return DatasetRegistered(
        dataset_id=uuid4(),
        execution_id=uuid4(),
        step_id=uuid4(),
        external_ref_scheme=_SCHEME,
        external_ref_value=_VALUE,
        occurred_at=_WHEN,
    )


def _described(genesis: DatasetRegistered, *entries: Entry) -> DatasetManifestRegistered:
    return DatasetManifestRegistered(
        dataset_id=genesis.dataset_id,
        external_ref_scheme=_SCHEME,
        external_ref_value=_VALUE,
        convention="dxchange",
        entries=entries,
        occurred_at=_LATER,
    )


def _stored(event: DatasetManifestRegistered) -> StoredEvent:
    return StoredEvent(
        position=2,
        event_id=uuid4(),
        stream_type="Dataset",
        stream_id=event.dataset_id,
        version=2,
        event_type="DatasetManifestRegistered",
        schema_version=1,
        payload=to_payload(event),
        correlation_id=uuid4(),
        causation_id=None,
        occurred_at=event.occurred_at,
        recorded_at=event.occurred_at,
    )


def test_an_entry_survives_the_trip_to_a_payload_and_back_with_its_absences() -> None:
    """A measured entry and an unmeasured one, through JSON and home.

    The absences are what this is really checking. A shape goes out as
    a list and comes back as a tuple, and an extent nobody supplied has
    to come back as nothing rather than as an empty one, or a reader
    cannot tell a container nobody measured from one measured as
    holding nothing.
    """
    measured = Entry(
        path="/exchange/data",
        extent=Extent(shape=(1800, 2048, 2048), capacity=(2000, 2048, 2048), dtype="uint16"),
        role="projections",
    )
    unmeasured = Entry(path="/measurement/sample", extent=None, role="experiment-context")
    event = _described(_registered(), measured, unmeasured)

    assert from_stored(_stored(event)) == event


def test_a_payload_holding_an_entry_outside_the_bounds_fails_to_deserialize() -> None:
    """A row nothing could have written does not fold into a record."""
    event = _described(_registered(), Entry(path="/exchange/data", extent=None, role=None))
    stored = _stored(event)
    stored.payload["entries"][0]["path"] = ""

    with pytest.raises(ValueError, match="Malformed DatasetManifestRegistered"):
        from_stored(stored)


def test_folding_a_description_leaves_the_copy_it_was_taken_of_and_when() -> None:
    genesis = _registered()
    entry = Entry(path="/exchange/data", extent=None, role="projections")

    dataset = fold([genesis, _described(genesis, entry)])

    assert dataset is not None
    assert dataset.description is not None
    assert dataset.description.manifest == Manifest(convention="dxchange", entries=(entry,))
    assert dataset.description.external_ref == Identifier(scheme=_SCHEME, value=_VALUE)
    assert dataset.description.described_at == _LATER


def test_a_later_look_replaces_the_earlier_one_rather_than_sitting_beside_it() -> None:
    genesis = _registered()
    frames = Entry(path="/exchange/data", extent=None, role="projections")
    angles = Entry(path="/exchange/theta", extent=None, role="projection-angles")

    dataset = fold([genesis, _described(genesis, frames), _described(genesis, frames, angles)])

    assert dataset is not None
    assert dataset.description is not None
    assert dataset.description.manifest.entries == (frames, angles)


def test_describing_a_dataset_leaves_its_addresses_and_its_run_untouched() -> None:
    genesis = _registered()
    before = fold([genesis])
    after = fold([genesis, _described(genesis, Entry(path="/x", extent=None, role=None))])

    assert before is not None
    assert after is not None
    assert (after.id, after.execution_id, after.step_id) == (
        before.id,
        before.execution_id,
        before.step_id,
    )
    assert after.external_refs == before.external_refs
