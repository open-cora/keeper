"""The decision that taking a proposal produces.

Four invariants, and three of them share an error class. The cases worth
separating are therefore about the diagnostic the error carries, because
that is the only thing telling a caller which of the three happened.
"""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest

from keeper.counsel.aggregates.proposal import (
    Proposal,
    ProposalCannotBeTakenError,
    ProposalNotFoundError,
    ProposalTaken,
)
from keeper.counsel.features.take_proposal import (
    TakeProposal,
    TakeProposalContext,
    decide,
)
from keeper.execution.aggregates.procedure import (
    AcquireStep,
    ComposedStep,
    MoveStep,
    ProcedureStep,
)

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 9, 19, 14, 30, tzinfo=UTC)
_PARAMETERS: dict[str, Any] = {"exposure_time_s": 0.1}


def _open_proposal(plan_id: UUID | None = None) -> Proposal:
    return Proposal(
        id=uuid4(),
        actor_id=uuid4(),
        plan_id=plan_id if plan_id is not None else uuid4(),
        parameters=dict(_PARAMETERS),
    )


def _taken(proposal: Proposal, *, by: UUID) -> Proposal:
    return Proposal(
        id=proposal.id,
        actor_id=proposal.actor_id,
        plan_id=proposal.plan_id,
        parameters=proposal.parameters,
        execution_id=uuid4(),
        step_id=by,
    )


def _acquisition_of(plan_id: UUID | None) -> TakeProposalContext:
    """The composed step behind the acquisition, as the handler found it.

    A plan of None is the move case: the step exists and was composed to
    drive a motor rather than to ask an engine for anything.
    """
    step: ProcedureStep = (
        MoveStep(record="2bmb:m1", to=0.0)
        if plan_id is None
        else AcquireStep(plan_id=plan_id, parameters={}, scopes=("2bmb:det:",))
    )
    return TakeProposalContext(composed=ComposedStep(id=uuid4(), step=step))


def _take(proposal_id: UUID, **overrides: object) -> TakeProposal:
    fields: dict[str, object] = {
        "proposal_id": proposal_id,
        "execution_id": uuid4(),
        "step_id": uuid4(),
    }
    fields.update(overrides)
    return TakeProposal(**fields)  # pyright: ignore[reportArgumentType]


def test_taking_an_open_proposal_emits_one_event() -> None:
    proposal = _open_proposal()
    execution_id = uuid4()
    step_id = uuid4()

    events = decide(
        proposal,
        _take(proposal.id, execution_id=execution_id, step_id=step_id),
        context=_acquisition_of(proposal.plan_id),
        now=_NOW,
    )

    assert events == [
        ProposalTaken(
            proposal_id=proposal.id,
            execution_id=execution_id,
            step_id=step_id,
            occurred_at=_NOW,
        )
    ]


def test_taking_a_proposal_that_was_never_made_is_refused() -> None:
    with pytest.raises(ProposalNotFoundError):
        decide(
            None,
            _take(uuid4()),
            context=_acquisition_of(uuid4()),
            now=_NOW,
        )


def test_taking_one_twice_is_refused_and_names_the_first_step() -> None:
    """The step and not the execution around it.

    An execution may hold a thousand steps, so naming it would tell a
    caller almost nothing about what already took the proposal.
    """
    first_step = uuid4()
    proposal = _taken(_open_proposal(), by=first_step)

    with pytest.raises(ProposalCannotBeTakenError) as caught:
        decide(
            proposal,
            _take(proposal.id),
            context=_acquisition_of(proposal.plan_id),
            now=_NOW,
        )

    assert caught.value.taken_by == first_step


def test_a_step_that_ran_a_different_plan_is_refused_and_names_both_plans() -> None:
    proposal = _open_proposal()
    other_plan = uuid4()

    with pytest.raises(ProposalCannotBeTakenError) as caught:
        decide(
            proposal,
            _take(proposal.id),
            context=_acquisition_of(other_plan),
            now=_NOW,
        )

    assert caught.value.proposed_plan_id == proposal.plan_id
    assert caught.value.step_plan_id == other_plan
    assert caught.value.taken_by is None


def test_a_move_cannot_take_a_proposal_and_is_not_reported_as_a_mismatch() -> None:
    """A move runs no plan, so the comparison below would refuse it too.

    What separates the two is the message. Told the step ran a different
    plan and given none to compare against, a caller goes looking for a
    closer acquisition; told the step runs no plan at all, it knows the
    reference itself is wrong.
    """
    proposal = _open_proposal()

    with pytest.raises(ProposalCannotBeTakenError, match="runs no plan") as caught:
        decide(
            proposal,
            _take(proposal.id),
            context=_acquisition_of(None),
            now=_NOW,
        )

    assert caught.value.step_plan_id is None
    assert caught.value.proposed_plan_id is None


def test_the_three_refusals_are_told_apart_by_what_the_error_carries() -> None:
    """One class, three causes, and the attributes discriminate them."""
    proposal = _open_proposal()
    taken = _taken(proposal, by=uuid4())

    with pytest.raises(ProposalCannotBeTakenError) as already:
        decide(taken, _take(taken.id), context=_acquisition_of(taken.plan_id), now=_NOW)
    with pytest.raises(ProposalCannotBeTakenError) as mismatch:
        decide(proposal, _take(proposal.id), context=_acquisition_of(uuid4()), now=_NOW)
    with pytest.raises(ProposalCannotBeTakenError) as move:
        decide(proposal, _take(proposal.id), context=_acquisition_of(None), now=_NOW)

    assert [
        (error.value.taken_by is None, error.value.step_plan_id is None)
        for error in (already, mismatch, move)
    ] == [(False, True), (True, False), (True, True)]


def test_a_step_dispatched_with_other_parameters_still_takes_the_proposal() -> None:
    """The plan is compared and nothing else is.

    What a step was dispatched with is not on its record at all: an
    execution copies the sentence and the plan, and the procedure keeps
    the rest. So this is not a comparison this decider declines to make,
    it is one the record cannot support, and the plan is what it can.
    """
    proposal = _open_proposal()

    events = decide(
        proposal,
        _take(proposal.id),
        context=_acquisition_of(proposal.plan_id),
        now=_NOW,
    )

    assert len(events) == 1


def test_the_event_is_stamped_with_the_moment_the_decider_was_given() -> None:
    """Which moment that is belongs to the handler, not here.

    The decider stamps `now` and never reads the command's reported
    time, the way every run transition's does. Choosing between a
    reported time and the clock is the handler's, and the test next to
    that handler is where the choice is pinned.
    """
    proposal = _open_proposal()

    events = decide(
        proposal,
        _take(proposal.id, occurred_at=datetime(2026, 9, 18, 6, 0, tzinfo=UTC)),
        context=_acquisition_of(proposal.plan_id),
        now=_NOW,
    )

    assert events[0].occurred_at == _NOW
