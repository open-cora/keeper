"""The Procedure aggregate: its step union, its fold, and its round trip.

The round trip is the load-bearing one. A step leaves as a dictionary
with a `kind` key and comes back as one of two classes, and the two
halves are written in different functions, so nothing but a test run
against both at once says they still agree.

The step checks matter for a second reason. A procedure is the only thing
here whose payload holds a nested structure rather than flat fields, so
it is the only aggregate where a stored row can be malformed inside a
list rather than at the top level.
"""

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest

from keeper.execution.aggregates.procedure import (
    PROCEDURE_BEAMLINE_MAX_LENGTH,
    PROCEDURE_MAX_SCOPES_PER_STEP,
    PROCEDURE_MAX_STEPS,
    PROCEDURE_NAME_MAX_LENGTH,
    PROCEDURE_STREAM_TYPE,
    AcquireStep,
    ComposedStep,
    InvalidProcedureBeamlineError,
    InvalidProcedureNameError,
    InvalidProcedureStepsError,
    MoveStep,
    ProcedureBeamline,
    ProcedureDefined,
    ProcedureName,
    ProcedureStep,
    fold,
    from_stored,
    to_payload,
    validated_steps,
)
from keeper.infrastructure.ports.event_store import StoredEvent

pytestmark = pytest.mark.unit

_WHEN = datetime(2026, 9, 24, 10, 30, tzinfo=UTC)
_PLAN_ID = uuid4()


def _stored(event_type: str, payload: dict[str, object]) -> StoredEvent:
    """A stored row carrying the given type and payload, envelope filled in."""
    return StoredEvent(
        position=1,
        event_id=uuid4(),
        stream_type=PROCEDURE_STREAM_TYPE,
        stream_id=uuid4(),
        version=1,
        event_type=event_type,
        schema_version=1,
        payload=dict(payload),
        correlation_id=uuid4(),
        causation_id=None,
        occurred_at=_WHEN,
        recorded_at=_WHEN,
    )


def _acquire(**overrides: Any) -> AcquireStep:
    fields: dict[str, Any] = {
        "plan_id": _PLAN_ID,
        "parameters": {"exposure_seconds": 0.2},
        "scopes": ("2bmb:m1",),
    }
    return AcquireStep(**(fields | overrides))


def _composed(*steps: ProcedureStep) -> tuple[ComposedStep, ...]:
    """Name each step, the way the decider does with ids from its ports."""
    return tuple(ComposedStep(id=uuid4(), step=step) for step in steps)


def _defined(
    name: str = "tomography",
    steps: tuple[ComposedStep, ...] | None = None,
    beamline: str = "2-bm",
) -> ProcedureDefined:
    return ProcedureDefined(
        procedure_id=uuid4(),
        procedure_name=name,
        beamline=beamline,
        steps=steps
        if steps is not None
        else _composed(MoveStep(record="2bmb:m1", to=1.0), _acquire()),
        occurred_at=_WHEN,
    )


def test_a_procedure_name_is_trimmed_on_construction() -> None:
    assert ProcedureName("  tomography  ").value == "tomography"


def test_a_procedure_name_that_is_only_whitespace_is_refused() -> None:
    with pytest.raises(InvalidProcedureNameError):
        ProcedureName("   ")


def test_a_procedure_name_over_the_length_bound_is_refused() -> None:
    with pytest.raises(InvalidProcedureNameError):
        ProcedureName("x" * (PROCEDURE_NAME_MAX_LENGTH + 1))


def test_a_procedure_beamline_is_trimmed_on_construction() -> None:
    assert ProcedureBeamline("  2-bm  ").value == "2-bm"


def test_a_procedure_beamline_that_is_empty_after_trimming_is_refused() -> None:
    """A procedure nothing can route is a procedure nothing can drive,
    which is why this is required rather than optional."""
    with pytest.raises(InvalidProcedureBeamlineError):
        ProcedureBeamline("   ")


def test_a_procedure_beamline_over_the_length_bound_is_refused() -> None:
    with pytest.raises(InvalidProcedureBeamlineError):
        ProcedureBeamline("x" * (PROCEDURE_BEAMLINE_MAX_LENGTH + 1))


def test_a_beamline_is_stored_as_written_and_checked_against_nothing() -> None:
    """There is no Beamline aggregate. A word nothing recognises is
    storable, and shows up as a dispatch no conductor asks for rather
    than as a refusal here."""
    procedure = fold([_defined(beamline="nowhere-at-all")])
    assert procedure is not None
    assert procedure.beamline == ProcedureBeamline("nowhere-at-all")


def test_the_stored_payload_carries_the_beamline_that_routes_a_dispatch() -> None:
    assert to_payload(_defined(beamline="7-bm"))["beamline"] == "7-bm"


def test_a_stored_row_whose_beamline_no_longer_passes_fails_the_fold() -> None:
    """The evolver re-validates on the way out, the way it does for the
    name, so a row nothing could write today does not quietly fold."""
    with pytest.raises(InvalidProcedureBeamlineError):
        fold([_defined(beamline="   ")])


def test_a_procedure_with_no_steps_is_refused() -> None:
    with pytest.raises(InvalidProcedureStepsError, match="at least one step"):
        validated_steps(())


def test_a_procedure_over_the_step_bound_is_refused() -> None:
    too_many = tuple(MoveStep(record="2bmb:m1", to=1.0) for _ in range(PROCEDURE_MAX_STEPS + 1))
    with pytest.raises(InvalidProcedureStepsError, match="at most"):
        validated_steps(too_many)


def test_a_move_naming_no_record_is_refused() -> None:
    with pytest.raises(InvalidProcedureStepsError, match="names no record"):
        validated_steps((MoveStep(record="   ", to=1.0),))


def test_a_move_record_is_trimmed() -> None:
    (step,) = validated_steps((MoveStep(record="  2bmb:m1  ", to=1.0),))
    assert isinstance(step, MoveStep)
    assert step.record == "2bmb:m1"


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_a_move_to_a_value_json_cannot_carry_is_refused(value: float) -> None:
    """A payload holding one of these does not survive the log. Refusing
    at definition beats writing a row that fails to load."""
    with pytest.raises(InvalidProcedureStepsError, match="JSON cannot carry"):
        validated_steps((MoveStep(record="2bmb:m1", to=value),))


def test_an_acquisition_declaring_no_devices_is_refused() -> None:
    """Nothing here can look inside a routine to work out what it drives,
    so a step that declared nothing would be believed to touch no
    hardware, and two of those can run over one motor."""
    with pytest.raises(InvalidProcedureStepsError, match="declaring no devices"):
        validated_steps((_acquire(scopes=()),))


def test_an_acquisition_over_the_scope_bound_is_refused() -> None:
    too_many = tuple(f"2bmb:m{i}" for i in range(PROCEDURE_MAX_SCOPES_PER_STEP + 1))
    with pytest.raises(InvalidProcedureStepsError, match="scopes"):
        validated_steps((_acquire(scopes=too_many),))


def test_an_acquisition_scope_that_is_empty_after_trimming_is_refused() -> None:
    with pytest.raises(InvalidProcedureStepsError, match="empty after trimming"):
        validated_steps((_acquire(scopes=("2bmb:m1", "   ")),))


def test_a_move_carries_no_declared_scopes_because_its_record_is_the_claim() -> None:
    """The asymmetry between the two kinds, asserted rather than assumed:
    a move is derivable and an acquisition is not."""
    assert not hasattr(MoveStep(record="2bmb:m1", to=1.0), "scopes")


def test_the_stored_payload_carries_the_name_under_a_qualified_key() -> None:
    payload = to_payload(_defined())
    assert payload["procedure_name"] == "tomography"
    assert "name" not in payload


def test_the_stored_payload_discriminates_the_two_step_kinds() -> None:
    payload = to_payload(_defined())
    steps: list[dict[str, Any]] = payload["steps"]
    assert [step["kind"] for step in steps] == ["move", "acquire"]


def test_folding_the_genesis_event_gives_the_procedure_it_describes() -> None:
    event = _defined()
    procedure = fold([event])
    assert procedure is not None
    assert procedure.id == event.procedure_id
    assert procedure.name == ProcedureName("tomography")
    assert procedure.steps == event.steps


def test_the_stored_payload_names_each_step_beside_its_own_keys() -> None:
    """Flat on the wire, and one object per step, which is what a stored
    row looked like before the ids arrived."""
    event = _defined()
    steps: list[dict[str, Any]] = to_payload(event)["steps"]
    assert [step["id"] for step in steps] == [str(composed.id) for composed in event.steps]


def test_a_stored_row_whose_step_carries_no_id_cannot_be_folded() -> None:
    """A row written before steps were named. Refused rather than given
    an id here: inventing one during a replay would mean two folds of one
    stream disagreeing about what an execution cites."""
    payload = to_payload(_defined())
    for step in payload["steps"]:
        del step["id"]
    with pytest.raises(ValueError, match="ProcedureDefined"):
        from_stored(_stored("ProcedureDefined", payload))


def test_a_procedure_finds_one_of_its_steps_by_the_id_it_was_composed_with() -> None:
    procedure = fold([_defined()])
    assert procedure is not None
    wanted = procedure.steps[1]
    assert procedure.step(wanted.id) is wanted


def test_a_procedure_asked_for_a_step_it_does_not_hold_answers_nothing() -> None:
    procedure = fold([_defined()])
    assert procedure is not None
    assert procedure.step(uuid4()) is None


def test_folding_an_empty_stream_gives_no_procedure() -> None:
    assert fold([]) is None


def test_an_event_survives_the_round_trip_through_its_stored_payload() -> None:
    event = _defined()
    assert from_stored(_stored("ProcedureDefined", to_payload(event))) == event


def test_a_stored_row_of_an_unknown_event_type_is_refused() -> None:
    with pytest.raises(ValueError, match="Unknown Procedure event_type"):
        from_stored(_stored("ProcedureRetired", {}))


def test_a_stored_row_naming_a_step_kind_this_version_cannot_read_is_refused() -> None:
    """A row written by a later version reaching an earlier one. Failing
    to load is the honest answer: a procedure folded with one step
    silently dropped is a different routine wearing the same id."""
    payload = to_payload(_defined())
    payload["steps"] = [{"id": str(uuid4()), "kind": "transfer", "destination": "somewhere"}]
    with pytest.raises(ValueError, match="ProcedureDefined"):
        from_stored(_stored("ProcedureDefined", payload))


def test_a_stored_row_missing_a_field_is_refused_by_event_not_by_field() -> None:
    payload = to_payload(_defined())
    del payload["procedure_name"]
    with pytest.raises(ValueError, match="ProcedureDefined"):
        from_stored(_stored("ProcedureDefined", payload))


def test_a_stored_row_whose_name_no_longer_passes_the_bound_fails_the_fold() -> None:
    """The evolver re-validates on the way out, so a row nothing could
    write today does not quietly fold into a procedure."""
    with pytest.raises(InvalidProcedureNameError):
        fold([_defined(name="   ")])


def test_a_stored_row_whose_steps_no_longer_pass_fails_the_fold() -> None:
    with pytest.raises(InvalidProcedureStepsError):
        fold([_defined(steps=_composed(_acquire(scopes=())))])
