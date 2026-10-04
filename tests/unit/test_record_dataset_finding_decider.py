"""The decision that recording a finding about a dataset produces.

Three invariants, and two deliberate non-refusals that are the point of
the slice: the same judgement may be reached again on better evidence,
and a dataset may carry several judgements at once because they are
about different things.
"""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from keeper.custody.aggregates.dataset import (
    DATASET_MAX_FINDINGS,
    Dataset,
    DatasetFindingRecorded,
    DatasetFindingsFullError,
    DatasetFindingUnchangedError,
    DatasetNotFoundError,
    Finding,
)
from keeper.custody.features.record_dataset_finding import RecordDatasetFinding, decide
from keeper.shared.identifier import Identifier
from keeper.shared.instant import InvalidOccurredAtError

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 10, 4, 16, 1, tzinfo=UTC)
_EARLIER = datetime(2026, 10, 4, 15, 28, tzinfo=UTC)
_BEAMLINE = Identifier(scheme="posix-file", value="/local1/scan_038.h5")

_SHORT = Finding(judgement="projections-short-of-plan", expected=128, arrived=100)
_NO_ANGLES = Finding(judgement="angles-never-recorded", expected=1, arrived=0)


def _dataset(*found: Finding) -> Dataset:
    return Dataset(
        id=uuid4(),
        execution_id=uuid4(),
        step_id=uuid4(),
        external_refs=(_BEAMLINE,),
        description=None,
        findings=found,
    )


def _command(held: Dataset, finding: Finding) -> RecordDatasetFinding:
    return RecordDatasetFinding(dataset_id=held.id, finding=finding)


def test_a_finding_about_a_dataset_nobody_has_judged_emits_one_event() -> None:
    held = _dataset()

    events = decide(held, _command(held, _SHORT), now=_NOW)

    assert events == [
        DatasetFindingRecorded(
            dataset_id=held.id,
            judgement="projections-short-of-plan",
            expected=128,
            arrived=100,
            occurred_at=_NOW,
        )
    ]


def test_a_finding_against_a_dataset_that_was_never_registered_is_refused() -> None:
    with pytest.raises(DatasetNotFoundError):
        decide(
            None,
            RecordDatasetFinding(dataset_id=uuid4(), finding=_SHORT),
            now=_NOW,
        )


def test_a_finding_repeating_what_the_record_already_says_is_refused() -> None:
    held = _dataset(_SHORT)

    with pytest.raises(DatasetFindingUnchangedError):
        decide(held, _command(held, _SHORT), now=_NOW)


def test_the_same_judgement_reached_on_different_counts_is_admitted() -> None:
    """The case the slice exists for, and the one a repeat check would eat.

    A description is allowed to be superseded, so a computation that
    looks again after the data changed reaches the same word with
    different numbers and has something new to say.
    """
    held = _dataset(_SHORT)
    better = Finding(judgement="projections-short-of-plan", expected=128, arrived=128)

    events = decide(held, _command(held, better), now=_NOW)

    assert [event.arrived for event in events] == [128]


def test_a_second_judgement_about_the_same_data_is_admitted_beside_the_first() -> None:
    """Two judgements are about different things and neither supersedes."""
    held = _dataset(_SHORT)

    events = decide(held, _command(held, _NO_ANGLES), now=_NOW)

    assert [event.judgement for event in events] == ["angles-never-recorded"]


def test_a_dataset_offered_more_judgements_than_it_may_carry_is_refused() -> None:
    held = _dataset(*(Finding(judgement=f"word-{n}", expected=1, arrived=1) for n in range(16)))

    with pytest.raises(DatasetFindingsFullError):
        decide(held, _command(held, _SHORT), now=_NOW)


def test_replacing_a_judgement_at_the_bound_is_admitted_because_it_adds_none() -> None:
    """The bound counts distinct judgements, not recordings.

    A computation that keeps looking would otherwise be locked out by
    its own history, which is the opposite of what the bound is for.
    """
    standing = tuple(
        Finding(judgement=f"word-{n}", expected=1, arrived=1) for n in range(DATASET_MAX_FINDINGS)
    )
    held = _dataset(*standing)

    events = decide(
        held,
        _command(held, Finding(judgement="word-0", expected=1, arrived=0)),
        now=_NOW,
    )

    assert [event.arrived for event in events] == [0]


def test_the_event_is_stamped_with_the_moment_the_decider_was_given() -> None:
    """Which moment that is belongs to the handler, not here.

    The decider is pure and takes one. A caller who reported when the
    conclusion was reached gets theirs, and one who did not gets the
    clock, and the handler is where that choice is made.
    """
    held = _dataset()

    events = decide(held, _command(held, _SHORT), now=_EARLIER)

    assert [event.occurred_at for event in events] == [_EARLIER]


def test_a_finding_reported_without_a_timezone_is_refused_at_the_command() -> None:
    with pytest.raises(InvalidOccurredAtError):
        RecordDatasetFinding(
            dataset_id=uuid4(),
            finding=_SHORT,
            occurred_at=datetime(2026, 10, 4, 16, 1),
        )
