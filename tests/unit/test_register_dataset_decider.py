"""The decision that registering a dataset produces.

One invariant, which makes the absences worth testing as much as the
rule. This decider takes no context, because nothing about the run enters
the decision, and it refuses nothing about the reference, because the
value object already did.
"""

from datetime import UTC, datetime, timedelta, timezone
from uuid import uuid4

import pytest

from keeper.custody.aggregates.dataset import (
    Dataset,
    DatasetAlreadyExistsError,
    DatasetRegistered,
)
from keeper.custody.features.register_dataset import RegisterDataset, decide
from keeper.shared.identifier import Identifier
from keeper.shared.instant import InvalidOccurredAtError

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 9, 19, 14, 30, tzinfo=UTC)
_REF = Identifier(scheme="tiled-node-path", value="raw/636de04a-2e43-4c1b")


def test_registering_on_an_empty_stream_emits_one_event() -> None:
    execution_id, step_id, new_id = uuid4(), uuid4(), uuid4()

    events = decide(
        None,
        RegisterDataset(execution_id=execution_id, step_id=step_id, external_ref=_REF),
        now=_NOW,
        new_id=new_id,
    )

    assert events == [
        DatasetRegistered(
            dataset_id=new_id,
            execution_id=execution_id,
            step_id=step_id,
            external_ref_scheme=_REF.scheme,
            external_ref_value=_REF.value,
            occurred_at=_NOW,
        )
    ]


def test_registering_onto_a_live_stream_is_refused() -> None:
    existing = Dataset(id=uuid4(), execution_id=uuid4(), step_id=uuid4(), external_ref=_REF)

    with pytest.raises(DatasetAlreadyExistsError):
        decide(
            existing,
            RegisterDataset(execution_id=uuid4(), step_id=uuid4(), external_ref=_REF),
            now=_NOW,
            new_id=uuid4(),
        )


def test_the_reference_is_split_into_the_two_strings_the_payload_carries() -> None:
    events = decide(
        None,
        RegisterDataset(execution_id=uuid4(), step_id=uuid4(), external_ref=_REF),
        now=_NOW,
        new_id=uuid4(),
    )

    assert events[0].external_ref_scheme == "tiled-node-path"
    assert events[0].external_ref_value == "raw/636de04a-2e43-4c1b"


def test_a_second_dataset_may_name_the_reference_another_one_already_holds() -> None:
    """Nothing here can see a sibling stream, so nothing here refuses this.

    Worth pinning rather than leaving implicit: it is the gap the derived
    idempotency key covers on the producer's side, and a reader of the
    decider should not have to infer that the check is missing on purpose.
    """
    first = decide(
        None,
        RegisterDataset(execution_id=uuid4(), step_id=uuid4(), external_ref=_REF),
        now=_NOW,
        new_id=uuid4(),
    )
    second = decide(
        None,
        RegisterDataset(execution_id=uuid4(), step_id=uuid4(), external_ref=_REF),
        now=_NOW,
        new_id=uuid4(),
    )

    assert first[0].external_ref_value == second[0].external_ref_value
    assert first[0].dataset_id != second[0].dataset_id


def test_a_claimed_time_without_an_offset_is_refused_when_the_command_is_built() -> None:
    """The refusal is the command's, not the decider's, so it fires early."""
    with pytest.raises(InvalidOccurredAtError):
        RegisterDataset(
            execution_id=uuid4(),
            step_id=uuid4(),
            external_ref=_REF,
            occurred_at=datetime(2026, 9, 19, 14, 30),
        )


def test_a_claimed_time_with_an_offset_is_stored_as_the_same_instant_in_utc() -> None:
    command = RegisterDataset(
        execution_id=uuid4(),
        step_id=uuid4(),
        external_ref=_REF,
        occurred_at=datetime(2026, 9, 19, 16, 30, tzinfo=timezone(timedelta(hours=2))),
    )

    assert command.occurred_at == datetime(2026, 9, 19, 14, 30, tzinfo=UTC)
