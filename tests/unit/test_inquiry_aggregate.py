"""The Inquiry aggregate: its three events, its fold, and the round trip.

Three events and three states, so there is a state machine with a branch in
it: an inquiry may reach Answered through Claimed or straight from Open. The
branch is the thing worth pinning, because every derivation of the status
downstream has to agree about it and each of them spells the rule
differently.

The other properties here are that both closed types are reconstructed on
the way out of the log rather than carried as the strings the payload holds,
and that the observation boundary survives the trip whole.
"""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from keeper.counsel.aggregates.inquiry import (
    INQUIRY_OBJECTIVE_MAX_LENGTH,
    Inquiry,
    InquiryAnswered,
    InquiryClaimed,
    InquiryConclusion,
    InquiryMade,
    InquiryObjective,
    InquiryStatus,
    InvalidInquiryObjectiveError,
    evolve,
    fold,
    from_stored,
    to_payload,
)
from keeper.infrastructure.ports.event_store import StoredEvent

pytestmark = pytest.mark.unit

_WHEN = datetime(2026, 9, 19, 14, 30, tzinfo=UTC)
_OBJECTIVE = "find the absorption edge"
_STEPS = 6


def _made(**overrides: object) -> InquiryMade:
    fields: dict[str, object] = {
        "inquiry_id": uuid4(),
        "actor_id": uuid4(),
        "execution_id": uuid4(),
        "objective": _OBJECTIVE,
        "execution_step_count": _STEPS,
        "occurred_at": _WHEN,
    }
    fields.update(overrides)
    return InquiryMade(**fields)  # pyright: ignore[reportArgumentType]


def _claimed(inquiry_id: object) -> InquiryClaimed:
    return InquiryClaimed(inquiry_id=inquiry_id, occurred_at=_WHEN)  # pyright: ignore[reportArgumentType]


def _answered(inquiry_id: object, **overrides: object) -> InquiryAnswered:
    fields: dict[str, object] = {
        "inquiry_id": inquiry_id,
        "conclusion": InquiryConclusion.STOP.value,
        "observed_step_count": _STEPS,
        "execution_ended": True,
        "proposal_id": None,
        "occurred_at": _WHEN,
    }
    fields.update(overrides)
    return InquiryAnswered(**fields)  # pyright: ignore[reportArgumentType]


def _stored(event: InquiryMade | InquiryClaimed | InquiryAnswered) -> StoredEvent:
    return StoredEvent(
        position=1,
        event_id=uuid4(),
        stream_type="Inquiry",
        stream_id=event.inquiry_id,
        version=1,
        event_type=type(event).__name__,
        schema_version=1,
        payload=to_payload(event),
        correlation_id=uuid4(),
        causation_id=None,
        occurred_at=event.occurred_at,
        recorded_at=event.occurred_at,
    )


def test_folding_an_empty_stream_gives_nothing() -> None:
    assert fold([]) is None


def test_folding_a_genesis_gives_an_open_inquiry_with_no_answer() -> None:
    made = _made()

    state = fold([made])

    assert state == Inquiry(
        id=made.inquiry_id,
        actor_id=made.actor_id,
        execution_id=made.execution_id,
        objective=InquiryObjective(_OBJECTIVE),
        execution_step_count=_STEPS,
        status=InquiryStatus.OPEN,
        conclusion=None,
        observed_step_count=None,
        execution_ended=None,
        proposal_id=None,
    )


def test_folding_a_claim_moves_an_inquiry_to_claimed_and_answers_nothing() -> None:
    made = _made()

    state = fold([made, _claimed(made.inquiry_id)])

    assert state is not None
    assert state.status is InquiryStatus.CLAIMED
    assert state.conclusion is None
    assert state.is_answered is False


def test_folding_an_answer_records_the_conclusion_and_the_boundary() -> None:
    made = _made()
    answered = _answered(
        made.inquiry_id,
        conclusion=InquiryConclusion.REFER.value,
        observed_step_count=2,
        execution_ended=False,
    )

    state = fold([made, _claimed(made.inquiry_id), answered])

    assert state is not None
    assert state.status is InquiryStatus.ANSWERED
    assert state.conclusion is InquiryConclusion.REFER
    assert (state.observed_step_count, state.execution_ended) == (2, False)
    assert state.is_answered is True


def test_an_inquiry_answered_without_a_claim_still_reaches_answered() -> None:
    """The branch in the state machine, and the state every downstream
    derivation of the status gets wrong in the same way if it asks whether
    a thinker claimed rather than whether one answered."""
    made = _made()

    state = fold([made, _answered(made.inquiry_id)])

    assert state is not None
    assert state.status is InquiryStatus.ANSWERED


def test_only_the_answered_status_reads_as_terminal() -> None:
    assert [status.is_terminal for status in InquiryStatus] == [False, False, True]


def test_an_answer_covering_every_step_reads_as_complete() -> None:
    made = _made()

    state = fold([made, _answered(made.inquiry_id, observed_step_count=_STEPS)])

    assert state is not None
    assert state.covers_every_step is True


def test_an_answer_covering_some_steps_does_not_read_as_complete() -> None:
    """The distinction the boundary exists to keep: the same conclusion
    from two of six is a weaker claim than from six of six, and after the
    execution moves on nothing else can tell them apart."""
    made = _made()

    state = fold([made, _answered(made.inquiry_id, observed_step_count=2)])

    assert state is not None
    assert state.covers_every_step is False


def test_an_unanswered_inquiry_does_not_read_as_covering_every_step() -> None:
    assert fold([_made()]).covers_every_step is False  # pyright: ignore[reportOptionalMemberAccess]


def test_a_propose_answer_carries_the_proposal_through_the_fold() -> None:
    made = _made()
    proposal_id = uuid4()

    state = fold(
        [
            made,
            _answered(
                made.inquiry_id,
                conclusion=InquiryConclusion.PROPOSE.value,
                proposal_id=proposal_id,
            ),
        ]
    )

    assert state is not None
    assert state.proposal_id == proposal_id


def test_every_event_survives_the_round_trip_through_the_log() -> None:
    made = _made()
    events = [
        made,
        _claimed(made.inquiry_id),
        _answered(
            made.inquiry_id,
            conclusion=InquiryConclusion.PROPOSE.value,
            observed_step_count=3,
            execution_ended=False,
            proposal_id=uuid4(),
        ),
    ]

    assert [from_stored(_stored(event)) for event in events] == events


def test_folding_stored_rows_gives_what_folding_the_events_gave() -> None:
    """The property the whole approach rests on, and the one a payload that
    quietly dropped a field would break while every event test passed."""
    made = _made()
    events = [made, _claimed(made.inquiry_id), _answered(made.inquiry_id)]

    assert fold([from_stored(_stored(event)) for event in events]) == fold(events)


def test_a_conclusion_outside_the_four_fails_at_the_fold() -> None:
    """The closed type is rebuilt on the way out, so a fifth word cannot
    reach a caller as a string nothing checked."""
    made = _made()

    with pytest.raises(ValueError, match="not a valid InquiryConclusion"):
        fold([made, _answered(made.inquiry_id, conclusion="Maybe")])


def test_an_objective_outside_its_bound_fails_at_the_fold() -> None:
    with pytest.raises(InvalidInquiryObjectiveError):
        fold([_made(objective="x" * (INQUIRY_OBJECTIVE_MAX_LENGTH + 1))])


def test_an_objective_is_stored_trimmed() -> None:
    assert InquiryObjective("  find the edge  ").value == "find the edge"


def test_an_empty_objective_is_refused() -> None:
    with pytest.raises(InvalidInquiryObjectiveError):
        InquiryObjective("   ")


def test_claiming_an_inquiry_that_was_never_made_is_refused() -> None:
    with pytest.raises(ValueError, match="InquiryClaimed"):
        evolve(None, _claimed(uuid4()))


def test_answering_an_inquiry_that_was_never_made_is_refused() -> None:
    with pytest.raises(ValueError, match="InquiryAnswered"):
        evolve(None, _answered(uuid4()))


def test_an_unknown_event_type_is_refused_rather_than_guessed() -> None:
    made = _made()
    stored = _stored(made)
    mangled = StoredEvent(
        position=stored.position,
        event_id=stored.event_id,
        stream_type=stored.stream_type,
        stream_id=stored.stream_id,
        version=stored.version,
        event_type="InquiryWithdrawn",
        schema_version=stored.schema_version,
        payload=stored.payload,
        correlation_id=stored.correlation_id,
        causation_id=stored.causation_id,
        occurred_at=stored.occurred_at,
        recorded_at=stored.recorded_at,
    )

    with pytest.raises(ValueError, match="Unknown Inquiry event_type"):
        from_stored(mangled)
