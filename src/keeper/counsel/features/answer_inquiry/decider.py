"""The decision: what answering an inquiry produces.

Update-style, so the state comes in already folded and `new_id` is absent:
this command names its stream rather than creating one.

Pure. No awaits, no ports, no clock.
"""

from datetime import datetime

from keeper.counsel.aggregates.inquiry import (
    Inquiry,
    InquiryAnswered,
    InquiryCannotBeAnsweredError,
    InquiryConclusion,
    InquiryNotFoundError,
    InquiryStatus,
    InvalidInquiryConclusionError,
    InvalidInquiryObservationError,
)
from keeper.counsel.features.answer_inquiry.command import AnswerInquiry


def decide(
    state: Inquiry | None,
    command: AnswerInquiry,
    *,
    now: datetime,
) -> list[InquiryAnswered]:
    """Decide the events produced by answering an inquiry.

    Invariants:
      - State must not be None, or no such question was put
        -> InquiryNotFoundError
      - The inquiry must not already have an answer
        -> InquiryCannotBeAnsweredError
      - The observed step count must be zero or more, and no more than the
        execution had -> InvalidInquiryObservationError
      - A Propose conclusion must carry a proposal, and the other three must
        not -> InvalidInquiryConclusionError

    **Answered from open as well as from claimed.** A thinker handed its
    question never claims one, and refusing its answer would lose a
    conclusion in order to enforce an ordering nothing needs.

    **Answering twice is refused, and that is a domain claim rather than a
    safety rail.** A second thinking about one execution is a second
    question: it was asked after seeing the first answer, possibly of a
    different model, and the record should say so as two inquiries rather
    than quietly replacing one conclusion with another. Refusing is also
    the reversible direction, since allowing it later costs a sentence and
    disallowing it later costs a migration.

    **The observation boundary is checked for impossibility and nothing
    more.** A thinker cannot have seen more steps than the execution has,
    because an execution's steps ride its genesis and their number never
    changes. Seeing fewer is ordinary and is the case the fields exist for.
    Whether the thinker really saw as many as it says is not checkable
    here and is not checkable anywhere: by the time this arrives the
    execution has moved on.

    **The two conclusion refusals are opposite mistakes** and share a
    class, so the class carries which one arrived. A `Propose` with no
    proposal is a thinker that advised and lost the advice; anything else
    with a proposal is a record claiming an arm it did not take. Both leave
    the same reader unable to trust the join, and neither is reachable by
    the thinker this was built for, so they are here to stop a second
    client inventing a shape.
    """
    if state is None:
        raise InquiryNotFoundError(command.inquiry_id)
    if state.status is InquiryStatus.ANSWERED:
        raise InquiryCannotBeAnsweredError(command.inquiry_id, state.status)
    if not 0 <= command.observed_step_count <= state.execution_step_count:
        raise InvalidInquiryObservationError(
            command.inquiry_id,
            command.observed_step_count,
            state.execution_step_count,
        )
    proposes = command.conclusion is InquiryConclusion.PROPOSE
    if proposes and command.proposal_id is None:
        raise InvalidInquiryConclusionError(
            command.inquiry_id,
            command.conclusion,
            cause="named no proposal",
        )
    if not proposes and command.proposal_id is not None:
        raise InvalidInquiryConclusionError(
            command.inquiry_id,
            command.conclusion,
            cause="named a proposal, which only Propose may do",
        )
    return [
        InquiryAnswered(
            inquiry_id=command.inquiry_id,
            conclusion=command.conclusion.value,
            observed_step_count=command.observed_step_count,
            execution_ended=command.execution_ended,
            proposal_id=command.proposal_id,
            occurred_at=now,
        )
    ]


__all__ = ["decide"]
