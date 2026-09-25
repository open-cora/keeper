"""The decision behind defining a procedure.

Pure, so every case here is a value in and a value or a refusal out. The
one worth reading closely is the parameter check: a procedure may acquire
several times, and a caller told only that one of its acquisitions is
wrong has to check each by hand.
"""

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest

from keeper.execution.aggregates.plan import Plan, PlanName
from keeper.execution.aggregates.procedure import (
    AcquireStep,
    ComposedStep,
    InvalidProcedureBeamlineError,
    InvalidProcedureNameError,
    InvalidProcedureParametersError,
    InvalidProcedureStepsError,
    MoveStep,
    Procedure,
    ProcedureAlreadyExistsError,
    ProcedureBeamline,
    ProcedureName,
    ProcedureStep,
)
from keeper.execution.features.define_procedure.command import DefineProcedure
from keeper.execution.features.define_procedure.context import DefineProcedureContext
from keeper.execution.features.define_procedure.decider import decide

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 9, 24, 11, 0, tzinfo=UTC)
_NEW_ID = uuid4()
_PLAN_ID = uuid4()

_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {"exposure_seconds": {"type": "number", "minimum": 0}},
    "required": ["exposure_seconds"],
}


def _context() -> DefineProcedureContext:
    return DefineProcedureContext(
        plans={_PLAN_ID: Plan(id=_PLAN_ID, name=PlanName("count"), parameters_schema=_SCHEMA)}
    )


def _acquire(**overrides: Any) -> AcquireStep:
    fields: dict[str, Any] = {
        "plan_id": _PLAN_ID,
        "parameters": {"exposure_seconds": 0.2},
        "scopes": ("2bmb:m1",),
    }
    return AcquireStep(**(fields | overrides))


def _command(
    *steps: ProcedureStep, name: str = "tomography", beamline: str = "  2-bm  "
) -> DefineProcedure:
    return DefineProcedure(
        name=name,
        beamline=beamline,
        steps=steps if steps else (MoveStep(record="2bmb:m1", to=1.0),),
    )


def _decide(command: DefineProcedure) -> list[Any]:
    return decide(
        None,
        command,
        context=_context(),
        now=_NOW,
        new_id=_NEW_ID,
        step_ids=[uuid4() for _ in command.steps],
    )


def test_defining_a_procedure_produces_one_genesis_event() -> None:
    (event,) = _decide(_command(MoveStep(record="2bmb:m1", to=1.0), _acquire()))
    assert event.procedure_id == _NEW_ID
    assert event.procedure_name == "tomography"
    assert event.occurred_at == _NOW


def test_the_event_carries_every_step_in_the_order_it_was_given() -> None:
    first = MoveStep(record="2bmb:m1", to=1.0)
    second = MoveStep(record="2bmb:m2", to=2.0)
    (event,) = _decide(_command(first, second, _acquire()))
    assert tuple(composed.step for composed in event.steps) == (first, second, _acquire())


def test_the_beamline_is_trimmed_onto_the_event() -> None:
    (event,) = _decide(_command())
    assert event.beamline == "2-bm"


def test_a_procedure_composed_for_no_beamline_is_refused() -> None:
    """Required, because a dispatch of it could be routed nowhere."""
    with pytest.raises(InvalidProcedureBeamlineError):
        _decide(_command(beamline="   "))


def test_the_name_is_trimmed_onto_the_event() -> None:
    (event,) = _decide(_command(name="  tomography  "))
    assert event.procedure_name == "tomography"


def test_defining_against_an_id_that_already_has_a_history_is_refused() -> None:
    existing = Procedure(
        id=_NEW_ID,
        name=ProcedureName("tomography"),
        beamline=ProcedureBeamline("2-bm"),
        steps=(ComposedStep(id=uuid4(), step=MoveStep(record="2bmb:m1", to=1.0)),),
    )
    with pytest.raises(ProcedureAlreadyExistsError):
        decide(
            existing,
            _command(),
            context=_context(),
            now=_NOW,
            new_id=_NEW_ID,
            step_ids=[uuid4()],
        )


def test_a_bad_name_is_refused_before_the_steps_are_looked_at() -> None:
    """Cheapest refusal first, and the one a caller can act on fastest."""
    with pytest.raises(InvalidProcedureNameError):
        _decide(_command(_acquire(scopes=()), name="   "))


def test_a_malformed_step_is_refused_before_any_parameters_are_checked() -> None:
    """A schema failure caused by a step that was never storable would
    send its caller to fix the wrong thing."""
    with pytest.raises(InvalidProcedureStepsError):
        _decide(_command(_acquire(scopes=(), parameters={"exposure_seconds": "not a number"})))


def test_an_acquisition_whose_parameters_miss_the_schema_is_refused() -> None:
    with pytest.raises(InvalidProcedureParametersError):
        _decide(_command(_acquire(parameters={"exposure_seconds": "not a number"})))


def test_an_acquisition_supplying_no_parameters_at_all_is_accepted() -> None:
    """The shared validator defers `required` to the point the values are
    acted on, so empty values pass whatever the schema asks for. That is
    the same posture reporting a run takes, and it is asserted here so
    the gap is visible rather than discovered at a beamline."""
    events = _decide(_command(_acquire(parameters={})))
    assert len(events) == 1


def test_the_refusal_names_which_step_failed() -> None:
    """A procedure may acquire several times. A caller told only that one
    of them is wrong has to check each."""
    with pytest.raises(InvalidProcedureParametersError) as caught:
        _decide(
            _command(
                MoveStep(record="2bmb:m1", to=1.0),
                _acquire(),
                _acquire(parameters={"exposure_seconds": -1}),
            )
        )
    assert caught.value.index == 2


def test_a_procedure_of_moves_alone_needs_no_plans_at_all() -> None:
    """The context is empty and nothing looks in it, because a move cites
    nothing."""
    events = decide(
        None,
        _command(MoveStep(record="2bmb:m1", to=1.0)),
        context=DefineProcedureContext(plans={}),
        now=_NOW,
        new_id=_NEW_ID,
        step_ids=[uuid4()],
    )
    assert len(events) == 1


def test_every_step_is_named_with_the_id_it_was_given_in_order() -> None:
    command = _command(MoveStep(record="2bmb:m1", to=1.0), _acquire())
    step_ids = [uuid4(), uuid4()]
    (event,) = decide(
        None,
        command,
        context=_context(),
        now=_NOW,
        new_id=_NEW_ID,
        step_ids=step_ids,
    )
    assert [composed.id for composed in event.steps] == step_ids


def test_two_steps_that_are_identical_are_still_named_apart() -> None:
    """What the ids buy over a position: a procedure may repeat a step,
    and an execution of it has to be able to say which one it means."""
    same = MoveStep(record="2bmb:m1", to=1.0)
    (event,) = _decide(_command(same, same))
    first, second = event.steps
    assert first.step == second.step
    assert first.id != second.id


def test_a_definition_given_the_wrong_number_of_step_ids_is_a_caller_bug() -> None:
    with pytest.raises(ValueError, match="one id per step"):
        decide(
            None,
            _command(MoveStep(record="2bmb:m1", to=1.0), _acquire()),
            context=_context(),
            now=_NOW,
            new_id=_NEW_ID,
            step_ids=[uuid4()],
        )
