"""Making an inquiry: the genesis, the objective, and the captured count.

Three things this decision does and one it deliberately does not. It mints
the record, it puts the objective through its value object, and it takes the
step count off the execution the handler loaded. It does not look at how far
that execution has got, which is the case an inquiry about a live procedure
depends on.
"""

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from keeper.counsel.aggregates.inquiry import (
    INQUIRY_OBJECTIVE_MAX_LENGTH,
    InquiryAlreadyExistsError,
    InquiryMade,
    InvalidInquiryObjectiveError,
    fold,
)
from keeper.counsel.features.make_inquiry import MakeInquiry, MakeInquiryContext
from keeper.counsel.features.make_inquiry import decide as decide_make
from keeper.execution.aggregates.execution import (
    DispatchedStep,
    Execution,
    ExecutionDispatched,
    ExecutionStatus,
)
from keeper.execution.aggregates.execution import fold as fold_execution

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 9, 23, 9, 30, tzinfo=UTC)
_NEW_ID = UUID(int=1)
_ACTOR_ID = UUID(int=2)
_EXECUTION_ID = UUID(int=3)
_PROCEDURE_ID = UUID(int=4)
_OBJECTIVE = "find the absorption edge"


def _execution(*, steps: int = 3) -> Execution:
    state = fold_execution(
        [
            ExecutionDispatched(
                execution_id=_EXECUTION_ID,
                procedure_id=_PROCEDURE_ID,
                procedure_name="align_then_scan",
                beamline="2-bm",
                steps=[
                    DispatchedStep(
                        id=uuid4(),
                        describes=f"move 2bmb:m{index} to 0.0",
                        procedure_step_id=uuid4(),
                    )
                    for index in range(steps)
                ],
                occurred_at=_NOW,
            )
        ]
    )
    assert state is not None
    return state


def _decide(
    *,
    objective: str = _OBJECTIVE,
    execution: Execution | None = None,
    state: object = None,
) -> list[InquiryMade]:
    return decide_make(
        state,  # pyright: ignore[reportArgumentType]
        MakeInquiry(execution_id=_EXECUTION_ID, objective=objective),
        context=MakeInquiryContext(execution=execution or _execution()),
        actor_id=_ACTOR_ID,
        now=_NOW,
        new_id=_NEW_ID,
    )


def test_decide_emits_inquiry_made_when_the_stream_is_empty() -> None:
    (event,) = _decide()

    assert event == InquiryMade(
        inquiry_id=_NEW_ID,
        actor_id=_ACTOR_ID,
        execution_id=_EXECUTION_ID,
        objective=_OBJECTIVE,
        execution_step_count=3,
        occurred_at=_NOW,
    )


def test_decide_takes_the_step_count_from_the_execution_rather_than_the_command() -> None:
    """The denominator of the observation boundary, and the one half of it
    this system can establish for itself. A caller that supplied its own
    could make a partial reading look complete."""
    (event,) = _decide(execution=_execution(steps=7))

    assert event.execution_step_count == 7


def test_decide_writes_the_authenticated_principal_as_the_asker() -> None:
    """Nothing on the command names an asker, so a caller cannot ask as
    somebody else, and the only way to see the field is on a read."""
    (event,) = _decide()

    assert event.actor_id == _ACTOR_ID


def test_decide_trims_the_objective_before_it_reaches_the_log() -> None:
    (event,) = _decide(objective="  find the edge  ")

    assert event.objective == "find the edge"


def test_decide_rejects_an_objective_longer_than_its_bound() -> None:
    with pytest.raises(InvalidInquiryObjectiveError):
        _decide(objective="x" * (INQUIRY_OBJECTIVE_MAX_LENGTH + 1))


def test_decide_rejects_an_objective_that_is_empty_after_trimming() -> None:
    """A question with no question is a record nobody can read the answer
    against, which is the whole reason this context spends a text column."""
    with pytest.raises(InvalidInquiryObjectiveError):
        _decide(objective="   ")


def test_decide_rejects_an_id_that_already_has_a_history() -> None:
    existing = fold(
        [
            InquiryMade(
                inquiry_id=_NEW_ID,
                actor_id=_ACTOR_ID,
                execution_id=_EXECUTION_ID,
                objective=_OBJECTIVE,
                execution_step_count=3,
                occurred_at=_NOW,
            )
        ]
    )

    with pytest.raises(InquiryAlreadyExistsError):
        _decide(state=existing)


def test_decide_allows_a_question_about_an_execution_that_is_still_walking() -> None:
    """Deliberate, and the case the aggregate is most useful for: somebody
    part way through a long procedure asking whether it is worth finishing.
    The answer reports how much it saw, so refusing here would enforce at
    the record what the reader can see for themselves."""
    walking = _execution()
    assert walking.status is ExecutionStatus.DISPATCHED

    (event,) = _decide(execution=walking)

    assert event.execution_id == _EXECUTION_ID
