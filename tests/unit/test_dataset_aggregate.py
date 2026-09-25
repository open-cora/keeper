"""The Dataset aggregate: its event, its fold, and the round trip between.

One event, so the interesting property is not the state machine, there is
none. It is that the reference survives the trip: a value object on the
way in, two flat strings in the payload, and a value object again coming
back out of the log.
"""

from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from keeper.custody.aggregates.dataset import (
    Dataset,
    DatasetRegistered,
    evolve,
    fold,
    from_stored,
    to_payload,
)
from keeper.infrastructure.ports.event_store import StoredEvent
from keeper.shared.identifier import Identifier, InvalidIdentifierError

pytestmark = pytest.mark.unit

_WHEN = datetime(2026, 9, 19, 14, 30, tzinfo=UTC)


def _registered(**overrides: object) -> DatasetRegistered:
    fields: dict[str, object] = {
        "dataset_id": uuid4(),
        "execution_id": uuid4(),
        "step_id": uuid4(),
        "external_ref_scheme": "tiled-node-path",
        "external_ref_value": "raw/636de04a-2e43-4c1b-8f99-2f0af326cb66",
        "occurred_at": _WHEN,
    }
    fields.update(overrides)
    return DatasetRegistered(**fields)  # pyright: ignore[reportArgumentType]


def _stored(event: DatasetRegistered) -> StoredEvent:
    return StoredEvent(
        position=1,
        event_id=uuid4(),
        stream_type="Dataset",
        stream_id=event.dataset_id,
        version=1,
        event_type="DatasetRegistered",
        schema_version=1,
        payload=to_payload(event),
        correlation_id=uuid4(),
        causation_id=None,
        occurred_at=event.occurred_at,
        recorded_at=event.occurred_at,
    )


def test_folding_an_empty_stream_gives_nothing() -> None:
    assert fold([]) is None


def test_folding_a_registration_gives_the_run_and_the_reference() -> None:
    event = _registered()

    dataset = fold([event])

    assert dataset == Dataset(
        id=event.dataset_id,
        execution_id=event.execution_id,
        step_id=event.step_id,
        external_ref=Identifier(
            scheme="tiled-node-path",
            value="raw/636de04a-2e43-4c1b-8f99-2f0af326cb66",
        ),
    )


def test_the_reference_comes_back_as_a_pair_rather_than_two_strings() -> None:
    dataset = evolve(None, _registered())

    assert isinstance(dataset.external_ref, Identifier)
    assert dataset.external_ref.scheme == "tiled-node-path"


def test_a_registration_survives_the_round_trip_through_a_stored_row() -> None:
    event = _registered()

    assert from_stored(_stored(event)) == event


def test_a_row_whose_reference_no_longer_passes_its_bounds_refuses_to_fold() -> None:
    """A payload can hold what the value object would now reject.

    The bound could be tightened, or a row could be written by a version
    that did not have one. Rebuilding through `Identifier` is what makes
    that a loud failure rather than a state nothing could have written.
    """
    with pytest.raises(InvalidIdentifierError):
        evolve(None, _registered(external_ref_value="   "))


def test_an_unknown_event_type_on_a_dataset_stream_is_refused() -> None:
    event = _registered()
    row = _stored(event)
    unknown = replace(row, event_type="DatasetWithdrawn")

    with pytest.raises(ValueError, match="Unknown Dataset event_type"):
        from_stored(unknown)


def test_a_malformed_payload_names_the_event_rather_than_the_field() -> None:
    event = _registered()
    row = _stored(event)
    broken = replace(row, payload={**row.payload, "step_id": "not-a-uuid"})

    with pytest.raises(ValueError, match="Malformed DatasetRegistered"):
        from_stored(broken)
