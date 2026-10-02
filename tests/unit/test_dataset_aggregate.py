"""The Dataset aggregate: its events, its fold, and the round trip between.

Two properties worth the file. That a reference survives the trip, as a
value object on the way in, two flat strings in the payload and a value
object again coming back out. And that addresses accumulate and drop
without the rest of the record moving, because that is the whole of the
state machine here: a dataset is a join that gains and loses places its
data can be read.
"""

from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from keeper.custody.aggregates.dataset import (
    Dataset,
    DatasetAddressRegistered,
    DatasetAddressWithdrawn,
    DatasetRegistered,
    evolve,
    fold,
    from_stored,
    to_payload,
)
from keeper.custody.aggregates.dataset.evolver import DatasetStreamOutOfOrderError
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
        external_refs=(
            Identifier(
                scheme="tiled-node-path",
                value="raw/636de04a-2e43-4c1b-8f99-2f0af326cb66",
            ),
        ),
    )


def test_the_reference_comes_back_as_a_pair_rather_than_two_strings() -> None:
    dataset = evolve(None, _registered())

    (only,) = dataset.external_refs
    assert isinstance(only, Identifier)
    assert only.scheme == "tiled-node-path"


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
    unknown = replace(row, event_type="DatasetUnheardOf")

    with pytest.raises(ValueError, match="Unknown Dataset event_type"):
        from_stored(unknown)


def test_a_malformed_payload_names_the_event_rather_than_the_field() -> None:
    event = _registered()
    row = _stored(event)
    broken = replace(row, payload={**row.payload, "step_id": "not-a-uuid"})

    with pytest.raises(ValueError, match="Malformed DatasetRegistered"):
        from_stored(broken)


_CENTRAL = Identifier(scheme="gpfs-file", value="/central/raw/636de04a.h5")
_BEAMLINE = Identifier(scheme="tiled-node-path", value="raw/636de04a-2e43-4c1b-8f99-2f0af326cb66")


def _address_registered(
    event: DatasetRegistered, ref: Identifier = _CENTRAL, **overrides: object
) -> DatasetAddressRegistered:
    fields: dict[str, object] = {
        "dataset_id": event.dataset_id,
        "external_ref_scheme": ref.scheme,
        "external_ref_value": ref.value,
        "copied_by_execution_id": None,
        "copied_by_step_id": None,
        "occurred_at": _WHEN,
    }
    fields.update(overrides)
    return DatasetAddressRegistered(**fields)  # pyright: ignore[reportArgumentType]


def _withdrawn(event: DatasetRegistered, ref: Identifier) -> DatasetAddressWithdrawn:
    return DatasetAddressWithdrawn(
        dataset_id=event.dataset_id,
        external_ref_scheme=ref.scheme,
        external_ref_value=ref.value,
        occurred_at=_WHEN,
    )


def test_a_copy_reported_elsewhere_is_held_beside_the_address_it_was_written_to() -> None:
    """Both at once is the state a move spends days in, not a transition.

    Reported as a swap, the record would say the data left the beamline
    disk it is still on, for the whole of the window in which something
    would want to read whichever copy it can reach.
    """
    registered = _registered()

    dataset = fold([registered, _address_registered(registered)])

    assert dataset is not None
    assert dataset.external_refs == (_BEAMLINE, _CENTRAL)


def test_withdrawing_one_copy_leaves_the_others_and_the_run_that_made_them() -> None:
    registered = _registered()

    dataset = fold([registered, _address_registered(registered), _withdrawn(registered, _BEAMLINE)])

    assert dataset is not None
    assert dataset.external_refs == (_CENTRAL,)
    assert dataset.execution_id == registered.execution_id
    assert dataset.step_id == registered.step_id


def test_a_dataset_whose_every_copy_is_gone_still_says_which_run_produced_it() -> None:
    """An empty tuple rather than a deleted row.

    The question this context exists to answer is what a run produced.
    Dropping the record when the last copy goes would answer it with
    silence, which reads as a run that produced nothing.
    """
    registered = _registered()

    dataset = fold([registered, _withdrawn(registered, _BEAMLINE)])

    assert dataset is not None
    assert dataset.external_refs == ()
    assert dataset.step_id == registered.step_id


def test_a_copy_reported_twice_at_one_address_folds_to_one_entry() -> None:
    """The decider refuses this; the fold must survive it anyway.

    A log is met by this function and a caller is met by the decider.
    Doubling an entry would hand every reader a duplicate, and refusing
    here would make a whole stream unreadable over one redundant row.
    """
    registered = _registered()

    dataset = fold([registered, _address_registered(registered), _address_registered(registered)])

    assert dataset is not None
    assert dataset.external_refs == (_BEAMLINE, _CENTRAL)


def test_withdrawing_an_address_the_dataset_never_had_changes_nothing() -> None:
    registered = _registered()
    absent = Identifier(scheme="gpfs-file", value="/central/nothing-here.h5")

    dataset = fold([registered, _withdrawn(registered, absent)])

    assert dataset is not None
    assert dataset.external_refs == (_BEAMLINE,)


def test_a_stream_whose_first_event_is_not_its_registration_refuses_to_fold() -> None:
    """Unreachable through any command, and loud rather than invented.

    Building a dataset out of that row would mint an execution and
    a step nothing recorded, and the record would then be
    indistinguishable from one somebody meant.
    """
    registered = _registered()

    with pytest.raises(DatasetStreamOutOfOrderError):
        fold([_address_registered(registered)])


def test_a_registered_address_survives_the_round_trip_through_a_stored_row() -> None:
    registered = _registered()
    event = _address_registered(registered)

    assert (
        from_stored(
            replace(
                _stored(registered),
                event_type="DatasetAddressRegistered",
                payload=to_payload(event),
            )
        )
        == event
    )


def test_an_address_that_cites_the_work_that_copied_it_keeps_both_ids() -> None:
    """Absent has to mean absent, so present has to survive the log.

    Most copies are made by facility movement that is not a principal
    here and cites nothing. The ones this system dispatched are reports
    it is owed, and the citation is the only thing that tells them apart.
    """
    registered = _registered()
    by_execution, by_step = uuid4(), uuid4()
    event = _address_registered(
        registered, copied_by_execution_id=by_execution, copied_by_step_id=by_step
    )

    came_back = from_stored(
        replace(
            _stored(registered), event_type="DatasetAddressRegistered", payload=to_payload(event)
        )
    )

    assert came_back == event
    assert isinstance(came_back, DatasetAddressRegistered)
    assert came_back.copied_by_execution_id == by_execution


def test_an_address_that_cites_nothing_comes_back_citing_nothing() -> None:
    registered = _registered()
    event = _address_registered(registered)

    came_back = from_stored(
        replace(
            _stored(registered), event_type="DatasetAddressRegistered", payload=to_payload(event)
        )
    )

    assert isinstance(came_back, DatasetAddressRegistered)
    assert came_back.copied_by_execution_id is None
    assert came_back.copied_by_step_id is None
