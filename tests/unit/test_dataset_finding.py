"""What a finding may hold, and that it survives the trip to a row.

The load-bearing test here is the first one. Every other rule in this
file is a bound somebody could argue about; that one is why a judgement
is allowed into this record while the numbers behind a reading are not,
and it is written as a field-set assertion so that widening the shape
is an act somebody has to come and defend rather than a field that
slips in.
"""

import dataclasses
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from keeper.custody.aggregates.dataset import (
    FINDING_JUDGEMENT_MAX_LENGTH,
    DatasetFindingRecorded,
    DatasetRegistered,
    Finding,
    InvalidFindingError,
    fold,
    from_stored,
    to_payload,
)
from keeper.infrastructure.ports.event_store import StoredEvent

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 10, 4, 16, 1, tzinfo=UTC)


def test_a_finding_has_no_field_that_could_hold_a_value_read_from_the_data() -> None:
    """A finding says what was concluded, never what the data reads.

    There is nowhere here to park a mean, a sigma or a signal-to-noise
    ratio. The two counts that are here are evidence for the judgement
    and were not computed from any value inside the container: one is
    what a computation expected and the other is what the record said
    arrived. A fourth field fails this, which is the intended cost.
    """
    assert [f.name for f in dataclasses.fields(Finding)] == ["judgement", "expected", "arrived"]


def test_a_blank_judgement_is_refused_because_it_says_nothing_to_act_on() -> None:
    with pytest.raises(InvalidFindingError):
        Finding(judgement="   ", expected=1, arrived=0)


def test_a_judgement_past_the_bound_is_refused_as_prose_rather_than_a_word() -> None:
    with pytest.raises(InvalidFindingError):
        Finding(judgement="x" * (FINDING_JUDGEMENT_MAX_LENGTH + 1), expected=1, arrived=0)


def test_a_judgement_at_the_bound_is_admitted() -> None:
    held = Finding(judgement="x" * FINDING_JUDGEMENT_MAX_LENGTH, expected=1, arrived=1)

    assert len(held.judgement) == FINDING_JUDGEMENT_MAX_LENGTH


@pytest.mark.parametrize(("expected", "arrived"), [(-1, 0), (0, -1)])
def test_a_count_cannot_be_negative_because_it_counts_things(expected: int, arrived: int) -> None:
    with pytest.raises(InvalidFindingError):
        Finding(judgement="projections-short-of-plan", expected=expected, arrived=arrived)


def test_a_thing_that_should_be_there_and_is_not_is_one_against_zero() -> None:
    """Presence is a count, which is what lets one shape carry both cases."""
    absent = Finding(judgement="angles-never-recorded", expected=1, arrived=0)

    assert (absent.expected, absent.arrived) == (1, 0)


def _stored(event: DatasetFindingRecorded) -> StoredEvent:
    return StoredEvent(
        position=2,
        event_id=uuid4(),
        stream_type="Dataset",
        stream_id=event.dataset_id,
        version=2,
        event_type="DatasetFindingRecorded",
        schema_version=1,
        payload=to_payload(event),
        correlation_id=uuid4(),
        causation_id=None,
        occurred_at=event.occurred_at,
        recorded_at=event.occurred_at,
    )


def test_a_finding_survives_the_round_trip_through_a_stored_payload() -> None:
    event = DatasetFindingRecorded(
        dataset_id=uuid4(),
        judgement="projections-short-of-plan",
        expected=128,
        arrived=100,
        occurred_at=_NOW,
    )

    read_back = from_stored(_stored(event))

    assert read_back == event


def test_folding_a_finding_leaves_it_on_the_dataset() -> None:
    dataset_id = uuid4()
    held = fold(
        [
            DatasetRegistered(
                dataset_id=dataset_id,
                execution_id=uuid4(),
                step_id=uuid4(),
                external_ref_scheme="posix-file",
                external_ref_value="/local1/scan_038.h5",
                occurred_at=_NOW,
            ),
            DatasetFindingRecorded(
                dataset_id=dataset_id,
                judgement="projections-short-of-plan",
                expected=128,
                arrived=100,
                occurred_at=_NOW,
            ),
        ]
    )

    assert held is not None
    assert held.findings == (
        Finding(judgement="projections-short-of-plan", expected=128, arrived=100),
    )


def test_folding_the_same_judgement_twice_replaces_it_rather_than_doubling_it() -> None:
    """The second look is the same statement with better evidence."""
    dataset_id = uuid4()
    held = fold(
        [
            DatasetRegistered(
                dataset_id=dataset_id,
                execution_id=uuid4(),
                step_id=uuid4(),
                external_ref_scheme="posix-file",
                external_ref_value="/local1/scan_038.h5",
                occurred_at=_NOW,
            ),
            DatasetFindingRecorded(
                dataset_id=dataset_id,
                judgement="projections-short-of-plan",
                expected=128,
                arrived=100,
                occurred_at=_NOW,
            ),
            DatasetFindingRecorded(
                dataset_id=dataset_id,
                judgement="projections-short-of-plan",
                expected=128,
                arrived=128,
                occurred_at=_NOW,
            ),
        ]
    )

    assert held is not None
    assert held.findings == (
        Finding(judgement="projections-short-of-plan", expected=128, arrived=128),
    )


def test_folding_two_judgements_keeps_both_in_the_order_they_arrived() -> None:
    dataset_id = uuid4()
    held = fold(
        [
            DatasetRegistered(
                dataset_id=dataset_id,
                execution_id=uuid4(),
                step_id=uuid4(),
                external_ref_scheme="posix-file",
                external_ref_value="/local1/scan_038.h5",
                occurred_at=_NOW,
            ),
            DatasetFindingRecorded(
                dataset_id=dataset_id,
                judgement="projections-short-of-plan",
                expected=128,
                arrived=100,
                occurred_at=_NOW,
            ),
            DatasetFindingRecorded(
                dataset_id=dataset_id,
                judgement="angles-never-recorded",
                expected=1,
                arrived=0,
                occurred_at=_NOW,
            ),
        ]
    )

    assert held is not None
    assert [found.judgement for found in held.findings] == [
        "projections-short-of-plan",
        "angles-never-recorded",
    ]
