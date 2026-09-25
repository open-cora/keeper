"""The Execution aggregate: its six events, its fold, and the round trip.

The first aggregate here whose state holds a collection rather than a
handful of scalars, so the properties worth pinning are about that: the
step list is fixed at the genesis and never grows, each step event
touches exactly one element, and nothing about the execution itself moves
when a step does.

The round trip matters for the same reason it does next door. The
genesis re-validates three things on the way back out of the log, so a
payload that could not be written today has to fail on read rather than
become state nothing checked.
"""

from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from keeper.execution.aggregates.execution import (
    DispatchedStep,
    Execution,
    ExecutionClaimed,
    ExecutionDispatched,
    ExecutionEnded,
    ExecutionEvent,
    ExecutionStatus,
    ExecutionStepBroken,
    ExecutionStepDone,
    ExecutionStepRefused,
    ExecutionStepSkipped,
    InvalidExecutionProcedureNameError,
    InvalidExecutionStepsError,
    StepOutcome,
    evolve,
    fold,
    from_stored,
    to_payload,
    validated_steps,
)
from keeper.infrastructure.ports.event_store import StoredEvent

pytestmark = pytest.mark.unit

_WHEN = datetime(2026, 9, 23, 9, 30, tzinfo=UTC)
_PROCEDURE_ID = UUID(int=7)
_PLAN_ID = UUID(int=9)
_STEPS = ["move 2bmb:m1 to 0.0", "acquire tomo_scan", "move 2bmb:m2 to 5.0"]
_COMPOSED = [uuid4(), uuid4(), uuid4()]
"""The ids of the procedure steps these were dispatched from.

Fixed at module scope, because the point of them is that they are the
same across every execution of one procedure, where the step ids in
`_steps` below are minted afresh per dispatch.
"""
"""Which step runs a plan, matched to `_STEPS` by position.

The middle one is the acquisition, so the round trip below carries both
a set plan and two unset ones. A fixture where every step was a move
would exercise only the null.
"""


def _steps() -> list[DispatchedStep]:
    """Freshly identified steps, because a step id is minted per dispatch."""
    return [
        DispatchedStep(id=uuid4(), describes=text, procedure_step_id=procedure_step_id)
        for text, procedure_step_id in zip(_STEPS, _COMPOSED, strict=True)
    ]


def _dispatched(**overrides: object) -> ExecutionDispatched:
    fields: dict[str, object] = {
        "execution_id": uuid4(),
        "procedure_id": _PROCEDURE_ID,
        "procedure_name": "align_then_scan",
        "beamline": "2-bm",
        "steps": _steps(),
        "occurred_at": _WHEN,
    }
    fields.update(overrides)
    return ExecutionDispatched(**fields)  # pyright: ignore[reportArgumentType]


def _stored(event: ExecutionEvent) -> StoredEvent:
    return StoredEvent(
        position=1,
        event_id=uuid4(),
        stream_type="Execution",
        stream_id=event.execution_id,
        version=1,
        event_type=type(event).__name__,
        schema_version=1,
        payload=to_payload(event),
        correlation_id=uuid4(),
        causation_id=None,
        occurred_at=event.occurred_at,
        recorded_at=event.occurred_at,
    )


def _walk(*events: ExecutionEvent) -> Execution:
    state = fold([_dispatched(execution_id=UUID(int=1)), *events])
    assert state is not None
    return state


def test_the_genesis_builds_a_step_for_every_step_it_names() -> None:
    state = _walk()
    assert state.step_count == 3
    assert [step.describes for step in state.steps] == _STEPS
    assert state.reported_count == 0
    assert not state.ended


def test_the_fold_keeps_the_composed_step_each_one_was_dispatched_from() -> None:
    """Every step cites one, a move as much as an acquisition.

    The fold rebuilds steps from the genesis payload, so a field dropped
    on the way through would leave a record that reads correctly and has
    forgotten what anything outside this context asks it.
    """
    state = _walk()
    assert [step.procedure_step_id for step in state.steps] == _COMPOSED


def test_a_walk_with_no_events_folds_to_none() -> None:
    assert fold([]) is None


def test_reporting_a_step_done_leaves_every_other_step_alone() -> None:
    state = _walk(
        ExecutionStepDone(
            execution_id=UUID(int=1), index=1, engine_reference="uid-7", occurred_at=_WHEN
        )
    )
    assert state.steps[1].outcome is StepOutcome.DONE
    assert state.steps[1].engine_reference == "uid-7"
    assert [step.outcome for step in state.steps] == [None, StepOutcome.DONE, None]
    assert state.reported_count == 1


def test_a_done_step_that_opened_no_run_carries_no_reference() -> None:
    """A move drives a motor and opens nothing, which is most steps."""
    state = _walk(
        ExecutionStepDone(
            execution_id=UUID(int=1), index=0, engine_reference=None, occurred_at=_WHEN
        )
    )
    assert state.steps[0].outcome is StepOutcome.DONE
    assert state.steps[0].engine_reference is None


def test_a_refused_step_records_the_outcome_and_no_detail() -> None:
    state = _walk(ExecutionStepRefused(execution_id=UUID(int=1), index=0, occurred_at=_WHEN))
    step = state.steps[0]
    assert step.outcome is StepOutcome.REFUSED
    assert (step.engine_reference, step.cause) == (None, None)


def test_a_broken_step_keeps_the_class_that_was_raised() -> None:
    state = _walk(
        ExecutionStepBroken(
            execution_id=UUID(int=1), index=1, cause="TimeoutError", occurred_at=_WHEN
        )
    )
    assert state.steps[1].outcome is StepOutcome.BROKEN
    assert state.steps[1].cause == "TimeoutError"


def test_a_skipped_step_carries_nothing_beyond_the_outcome() -> None:
    state = _walk(ExecutionStepSkipped(execution_id=UUID(int=1), index=2, occurred_at=_WHEN))
    step = state.steps[2]
    assert step.outcome is StepOutcome.SKIPPED
    assert (step.engine_reference, step.cause) == (None, None)


def test_ending_a_walk_moves_nothing_but_the_ending() -> None:
    before = _walk(
        ExecutionStepDone(
            execution_id=UUID(int=1), index=0, engine_reference=None, occurred_at=_WHEN
        )
    )
    after = evolve(before, ExecutionEnded(execution_id=UUID(int=1), occurred_at=_WHEN))
    assert after.status is ExecutionStatus.ENDED
    assert after.steps == before.steps
    assert (after.procedure_id, after.procedure_name) == (
        before.procedure_id,
        before.procedure_name,
    )


def test_a_walk_can_end_with_steps_still_unreported() -> None:
    """What a record left behind by a driver that died looks like."""
    state = _walk(
        ExecutionStepDone(
            execution_id=UUID(int=1), index=0, engine_reference=None, occurred_at=_WHEN
        ),
        ExecutionEnded(execution_id=UUID(int=1), occurred_at=_WHEN),
    )
    assert state.ended
    assert (state.reported_count, state.step_count) == (1, 3)


@pytest.mark.parametrize(
    "event",
    [
        _dispatched(execution_id=UUID(int=1)),
        ExecutionStepDone(
            execution_id=UUID(int=1), index=0, engine_reference="uid-7", occurred_at=_WHEN
        ),
        ExecutionStepDone(
            execution_id=UUID(int=1), index=0, engine_reference=None, occurred_at=_WHEN
        ),
        ExecutionStepRefused(execution_id=UUID(int=1), index=0, occurred_at=_WHEN),
        ExecutionStepBroken(
            execution_id=UUID(int=1), index=0, cause="TimeoutError", occurred_at=_WHEN
        ),
        ExecutionStepSkipped(execution_id=UUID(int=1), index=0, occurred_at=_WHEN),
        ExecutionEnded(execution_id=UUID(int=1), occurred_at=_WHEN),
    ],
    ids=lambda event: type(event).__name__,
)
def test_every_event_survives_a_round_trip_through_the_store(event: ExecutionEvent) -> None:
    assert from_stored(_stored(event)) == event


def test_an_unknown_event_type_is_refused_rather_than_guessed_at() -> None:
    stored = replace(_stored(_dispatched()), event_type="WalkWandered")
    with pytest.raises(ValueError, match="Unknown Execution event_type"):
        from_stored(stored)


def test_a_dispatched_walk_folds_to_the_dispatched_status() -> None:
    state = fold([_dispatched()])
    assert state is not None
    assert state.status is ExecutionStatus.DISPATCHED
    assert not state.ended


def test_claiming_a_walk_moves_it_off_dispatched_and_touches_nothing_else() -> None:
    before = fold([_dispatched(execution_id=UUID(int=1))])
    assert before is not None
    after = evolve(before, ExecutionClaimed(execution_id=UUID(int=1), occurred_at=_WHEN))
    assert after.status is ExecutionStatus.CLAIMED
    assert after.steps == before.steps


def test_the_first_step_report_makes_a_walk_running() -> None:
    """Reported without a claim, because claiming says who has the work
    and is not a gate on reporting."""
    state = _walk(
        ExecutionStepDone(
            execution_id=UUID(int=1), index=0, engine_reference=None, occurred_at=_WHEN
        )
    )
    assert state.status is ExecutionStatus.RUNNING


def test_a_stored_genesis_whose_name_no_longer_passes_fails_on_read() -> None:
    with pytest.raises(InvalidExecutionProcedureNameError):
        fold([_dispatched(procedure_name="   ")])


def test_a_stored_genesis_whose_steps_no_longer_pass_fails_on_read() -> None:
    with pytest.raises(InvalidExecutionStepsError):
        fold([_dispatched(steps=[])])


def test_a_step_event_on_an_empty_stream_says_the_log_is_out_of_order() -> None:
    with pytest.raises(ValueError, match="ExecutionStepDone"):
        evolve(
            None,
            ExecutionStepDone(
                execution_id=uuid4(), index=0, engine_reference=None, occurred_at=_WHEN
            ),
        )


def _dispatched_steps(*described: str) -> tuple[DispatchedStep, ...]:
    return tuple(
        DispatchedStep(id=uuid4(), describes=text, procedure_step_id=uuid4()) for text in described
    )


def test_steps_are_trimmed_on_the_way_in() -> None:
    (step,) = validated_steps(_dispatched_steps("  move m1  "))
    assert step.describes == "move m1"


def test_trimming_a_step_keeps_the_id_it_was_dispatched_with() -> None:
    """A dataset points at a step id, so trimming the text must not mint
    a new one and orphan whatever already cited it."""
    given = _dispatched_steps("  move m1  ")
    (step,) = validated_steps(given)
    assert step.id == given[0].id


def test_a_step_list_with_a_blank_entry_is_refused() -> None:
    with pytest.raises(InvalidExecutionStepsError, match="Step 1"):
        validated_steps(_dispatched_steps("move m1", "   "))


def test_a_step_list_past_the_bound_is_refused() -> None:
    with pytest.raises(InvalidExecutionStepsError, match="at most"):
        validated_steps(_dispatched_steps(*(f"move m{n}" for n in range(1001))))


def test_a_step_longer_than_the_bound_is_refused() -> None:
    with pytest.raises(InvalidExecutionStepsError, match="the bound is"):
        validated_steps(_dispatched_steps("x" * 501))
