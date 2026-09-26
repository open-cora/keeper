"""Claiming and answering: the two transitions, and what each refuses.

They are here together because what they refuse only makes sense side by
side. A claim is refused from everything but open; an answer is refused only
from answered. That asymmetry is the whole of the claim's status in this
lifecycle, and testing either one alone would leave it looking arbitrary.

The other thing pinned here is the pair of rules on the answer that no field
constraint can express: the observation boundary must be possible, and only
Propose may carry a proposal.
"""

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from keeper.counsel.aggregates.inquiry import (
    Inquiry,
    InquiryAnswered,
    InquiryCannotBeAnsweredError,
    InquiryCannotBeClaimedError,
    InquiryClaimed,
    InquiryConclusion,
    InquiryMade,
    InquiryNotFoundError,
    InquiryStatus,
    InvalidInquiryConclusionError,
    InvalidInquiryObservationError,
    fold,
)
from keeper.counsel.features.answer_inquiry import AnswerInquiry
from keeper.counsel.features.answer_inquiry import decide as decide_answer
from keeper.counsel.features.claim_inquiry import ClaimInquiry
from keeper.counsel.features.claim_inquiry import decide as decide_claim

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 9, 23, 9, 30, tzinfo=UTC)
_ID = UUID(int=1)
_ACTOR_ID = UUID(int=2)
_EXECUTION_ID = UUID(int=3)
_STEPS = 6


def _live(*, claimed: bool = False, answered: bool = False) -> Inquiry:
    events: list[object] = [
        InquiryMade(
            inquiry_id=_ID,
            actor_id=_ACTOR_ID,
            execution_id=_EXECUTION_ID,
            objective="find the absorption edge",
            execution_step_count=_STEPS,
            occurred_at=_NOW,
        )
    ]
    if claimed:
        events.append(InquiryClaimed(inquiry_id=_ID, occurred_at=_NOW))
    if answered:
        events.append(
            InquiryAnswered(
                inquiry_id=_ID,
                conclusion=InquiryConclusion.STOP.value,
                observed_step_count=_STEPS,
                execution_ended=True,
                proposal_id=None,
                occurred_at=_NOW,
            )
        )
    state = fold(events)  # pyright: ignore[reportArgumentType]
    assert state is not None
    return state


def _answer(**overrides: object) -> AnswerInquiry:
    fields: dict[str, object] = {
        "inquiry_id": _ID,
        "conclusion": InquiryConclusion.STOP,
        "observed_step_count": _STEPS,
        "execution_ended": True,
        "proposal_id": None,
    }
    fields.update(overrides)
    return AnswerInquiry(**fields)  # pyright: ignore[reportArgumentType]


def test_decide_claim_emits_inquiry_claimed_when_the_inquiry_is_open() -> None:
    (event,) = decide_claim(_live(), ClaimInquiry(inquiry_id=_ID), now=_NOW)

    assert event == InquiryClaimed(inquiry_id=_ID, occurred_at=_NOW)


def test_decide_claim_rejects_an_inquiry_that_was_never_made() -> None:
    with pytest.raises(InquiryNotFoundError):
        decide_claim(None, ClaimInquiry(inquiry_id=_ID), now=_NOW)


def test_decide_claim_rejects_a_second_claim_on_one_question() -> None:
    """Two thinkers each believing they have it, which is the failure the
    middle state exists to make visible. Nothing here can stop the second
    from calling a model anyway; what it can do is keep the disagreement
    out of the record."""
    with pytest.raises(InquiryCannotBeClaimedError) as refused:
        decide_claim(_live(claimed=True), ClaimInquiry(inquiry_id=_ID), now=_NOW)

    assert refused.value.status is InquiryStatus.CLAIMED


def test_decide_claim_rejects_a_claim_on_an_answered_inquiry() -> None:
    """A different fact from the one above, and the status is what tells
    them apart: this is a thinker starting work somebody else finished."""
    with pytest.raises(InquiryCannotBeClaimedError) as refused:
        decide_claim(_live(answered=True), ClaimInquiry(inquiry_id=_ID), now=_NOW)

    assert refused.value.status is InquiryStatus.ANSWERED


def test_decide_answer_emits_inquiry_answered_from_a_claimed_inquiry() -> None:
    (event,) = decide_answer(_live(claimed=True), _answer(), now=_NOW)

    assert event == InquiryAnswered(
        inquiry_id=_ID,
        conclusion=InquiryConclusion.STOP.value,
        observed_step_count=_STEPS,
        execution_ended=True,
        proposal_id=None,
        occurred_at=_NOW,
    )


def test_decide_answer_accepts_an_inquiry_nobody_claimed() -> None:
    """Claiming is not a gate on answering. A thinker handed its question
    never claims, and refusing its answer would lose a conclusion in order
    to enforce an ordering the log does not have."""
    (event,) = decide_answer(_live(), _answer(), now=_NOW)

    assert event.conclusion == InquiryConclusion.STOP.value


def test_decide_answer_rejects_an_inquiry_that_was_never_made() -> None:
    with pytest.raises(InquiryNotFoundError):
        decide_answer(None, _answer(), now=_NOW)


def test_decide_answer_rejects_a_second_answer_on_one_question() -> None:
    """A second thinking is a second question: it was asked after seeing
    the first answer, so the record should hold two inquiries rather than
    quietly replace one conclusion with another."""
    with pytest.raises(InquiryCannotBeAnsweredError) as refused:
        decide_answer(_live(answered=True), _answer(), now=_NOW)

    assert refused.value.status is InquiryStatus.ANSWERED


def test_decide_answer_rejects_seeing_more_steps_than_the_execution_has() -> None:
    """The one half of the observation boundary this system can check. An
    execution's steps ride its genesis, so their number never changes and
    a larger count cannot describe any reading of it."""
    with pytest.raises(InvalidInquiryObservationError) as refused:
        decide_answer(_live(), _answer(observed_step_count=_STEPS + 1), now=_NOW)

    assert (refused.value.observed, refused.value.of) == (_STEPS + 1, _STEPS)


def test_decide_answer_rejects_a_negative_observation() -> None:
    with pytest.raises(InvalidInquiryObservationError):
        decide_answer(_live(), _answer(observed_step_count=-1), now=_NOW)


def test_decide_answer_accepts_having_seen_none_of_the_steps() -> None:
    """Zero is a real reading rather than a missing one: an execution
    nothing has reported against yet is exactly what a thinker asked early
    has in front of it."""
    (event,) = decide_answer(_live(), _answer(observed_step_count=0), now=_NOW)

    assert event.observed_step_count == 0


def test_decide_answer_rejects_a_propose_that_names_no_proposal() -> None:
    """A thinker that advised and lost the advice. The pair of refusals
    below are opposite mistakes and share a class, so the cause is what a
    caller reads to tell which half to fix."""
    with pytest.raises(InvalidInquiryConclusionError) as refused:
        decide_answer(_live(), _answer(conclusion=InquiryConclusion.PROPOSE), now=_NOW)

    assert refused.value.cause == "named no proposal"


def test_decide_answer_rejects_any_other_conclusion_that_names_a_proposal() -> None:
    with pytest.raises(InvalidInquiryConclusionError) as refused:
        decide_answer(
            _live(),
            _answer(conclusion=InquiryConclusion.ABSTAIN, proposal_id=uuid4()),
            now=_NOW,
        )

    assert refused.value.cause == "named a proposal, which only Propose may do"


def test_decide_answer_carries_the_proposal_on_the_propose_arm() -> None:
    proposal_id = uuid4()

    (event,) = decide_answer(
        _live(),
        _answer(conclusion=InquiryConclusion.PROPOSE, proposal_id=proposal_id),
        now=_NOW,
    )

    assert (event.conclusion, event.proposal_id) == (
        InquiryConclusion.PROPOSE.value,
        proposal_id,
    )


@pytest.mark.parametrize(
    "conclusion",
    [InquiryConclusion.STOP, InquiryConclusion.ABSTAIN, InquiryConclusion.REFER],
)
def test_decide_answer_records_every_conclusion_that_writes_nothing_elsewhere(
    conclusion: InquiryConclusion,
) -> None:
    """The three arms this aggregate exists for. Before it they reached
    nothing at all, so a thinker that concluded any of them left the
    record saying only that it had never run."""
    (event,) = decide_answer(_live(), _answer(conclusion=conclusion), now=_NOW)

    assert event.conclusion == conclusion.value
