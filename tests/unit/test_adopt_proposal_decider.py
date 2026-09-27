"""Adopting a proposal: the one arm of three that belongs to this stream.

The slice writes a procedure, an execution and this, and the other two
are decided by Execution's own deciders. So what is checked here is the
proposal's half: that it is refused unless the proposal is open, and
that what it writes is the acquisition the same transaction is about to
create.

What is deliberately NOT checked here is the beamline and the devices.
Both are refused by `define_procedure`, which runs before this in the
handler, and repeating those refusals here would be this context
holding an opinion about a bound another context enforces.
"""

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from keeper.counsel.aggregates.proposal import (
    Proposal,
    ProposalAdopted,
    ProposalCannotBeAdoptedError,
    ProposalMade,
    ProposalNotFoundError,
    ProposalStatus,
    ProposalTaken,
    fold,
)
from keeper.counsel.features.adopt_proposal import AdoptProposal
from keeper.counsel.features.adopt_proposal import decide as decide_adopt

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 9, 26, 9, 30, tzinfo=UTC)
_ID = UUID(int=1)
_ACTOR_ID = UUID(int=2)
_PLAN_ID = UUID(int=3)
_EXECUTION_ID = UUID(int=4)
_STEP_ID = UUID(int=5)


def _live(*, taken: bool = False, adopted: bool = False) -> Proposal:
    events: list[object] = [
        ProposalMade(
            proposal_id=_ID,
            actor_id=_ACTOR_ID,
            plan_id=_PLAN_ID,
            parameters={},
            occurred_at=_NOW,
        )
    ]
    if taken:
        events.append(
            ProposalTaken(proposal_id=_ID, execution_id=uuid4(), step_id=uuid4(), occurred_at=_NOW)
        )
    if adopted:
        events.append(
            ProposalAdopted(
                proposal_id=_ID, execution_id=uuid4(), step_id=uuid4(), occurred_at=_NOW
            )
        )
    state = fold(events)  # pyright: ignore[reportArgumentType]
    assert state is not None
    return state


def _command() -> AdoptProposal:
    return AdoptProposal(proposal_id=_ID, beamline="2-bm", scopes=("2bmb:det:",))


def _decide(state: Proposal | None) -> list[ProposalAdopted]:
    return decide_adopt(
        state,
        _command(),
        execution_id=_EXECUTION_ID,
        step_id=_STEP_ID,
        now=_NOW,
    )


def test_decide_emits_proposal_adopted_when_the_proposal_is_open() -> None:
    (event,) = _decide(_live())

    assert event == ProposalAdopted(
        proposal_id=_ID,
        execution_id=_EXECUTION_ID,
        step_id=_STEP_ID,
        occurred_at=_NOW,
    )


def test_decide_names_the_acquisition_the_same_transaction_is_creating() -> None:
    """The ids are not the caller's and not loaded from anywhere: they
    were minted moments earlier for records this append will write."""
    (event,) = _decide(_live())

    assert (event.execution_id, event.step_id) == (_EXECUTION_ID, _STEP_ID)


def test_decide_rejects_a_proposal_that_was_never_made() -> None:
    with pytest.raises(ProposalNotFoundError):
        _decide(None)


def test_decide_rejects_adopting_one_that_is_already_adopted() -> None:
    """A second commitment of the facility to one piece of advice."""
    with pytest.raises(ProposalCannotBeAdoptedError) as refused:
        _decide(_live(adopted=True))

    assert refused.value.status is ProposalStatus.ADOPTED


def test_decide_rejects_adopting_one_something_else_already_ran() -> None:
    """A different fact from the one above, and the status is what tells
    them apart: here composing more work would run it a second time."""
    with pytest.raises(ProposalCannotBeAdoptedError) as refused:
        _decide(_live(taken=True))

    assert refused.value.status is ProposalStatus.TAKEN


def test_decide_carries_no_timestamp_from_the_caller() -> None:
    """Adopting is an act this system performs, so the clock's reading is
    the moment, and the command has nowhere to put an earlier one."""
    assert not hasattr(_command(), "occurred_at")
