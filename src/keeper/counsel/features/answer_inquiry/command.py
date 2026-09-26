"""The intent: record what a thinker concluded, and how much it had seen."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from keeper.counsel.aggregates.inquiry import InquiryConclusion
from keeper.shared.instant import normalize_occurred_at


@dataclass(frozen=True)
class AnswerInquiry:
    """Record this conclusion against this question, from this much of it.

    Answer, not conclude. The concluding happened in a thinker, over a
    model this system never saw; what arrives here is the answer to a
    question this system holds. Naming the command after the cognition
    would claim the cognition, which is the objection that kept the
    Proposal aggregate from being called a Decision.

    `conclusion` arrives as the closed type rather than as a string,
    because a caller sending a fifth word is sending something this system
    has no meaning for and the wire layer should refuse it before a decider
    has to.

    `observed_step_count` and `execution_ended` are the observation
    boundary, and they are required rather than optional. A conclusion
    drawn from two steps of six is a weaker claim than the same conclusion
    drawn from six of six, and once the execution moves on nothing can
    recover which it was. Leaving them out would have made the record
    silently unable to answer the question it was built to answer.

    They are the caller's claims and nothing here can check them, for the
    same reason: the reading they describe is over. What the decider checks
    is that they are not impossible.

    `proposal_id` is the proposal this conclusion wrote, and it belongs
    with `Propose` and with nothing else. The proposal is made first, on
    its own stream, and named here.

    `occurred_at` is when the thinking finished, as the caller reports it,
    and a caller who omits it gets the moment the report arrived.
    """

    inquiry_id: UUID
    conclusion: InquiryConclusion
    observed_step_count: int
    execution_ended: bool
    proposal_id: UUID | None = None
    occurred_at: datetime | None = None

    def __post_init__(self) -> None:
        """Refuse a naive timestamp and store the UTC form of an aware one.

        Frozen, so the normalised value goes back through
        `object.__setattr__`, the way the shared identifier does it.
        """
        if self.occurred_at is not None:
            object.__setattr__(self, "occurred_at", normalize_occurred_at(self.occurred_at))


__all__ = ["AnswerInquiry"]
