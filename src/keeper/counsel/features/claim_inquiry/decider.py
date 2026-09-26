"""The decision: what claiming an inquiry produces.

Update-style, so the state comes in already folded and `new_id` is absent:
this command names its stream rather than creating one.

Pure. No awaits, no ports, no clock. `now` arrives as a parameter precisely
so this function has nothing to invent.
"""

from datetime import datetime

from keeper.counsel.aggregates.inquiry import (
    Inquiry,
    InquiryCannotBeClaimedError,
    InquiryClaimed,
    InquiryNotFoundError,
    InquiryStatus,
)
from keeper.counsel.features.claim_inquiry.command import ClaimInquiry


def decide(
    state: Inquiry | None,
    command: ClaimInquiry,
    *,
    now: datetime,
) -> list[InquiryClaimed]:
    """Decide the events produced by claiming an inquiry.

    Invariants:
      - State must not be None, or no such question was put
        -> InquiryNotFoundError
      - The inquiry must be open and not yet taken up
        -> InquiryCannotBeClaimedError

    Refused from both of the other statuses, and they mean different
    things. A claim on an answered inquiry is a thinker that started work
    somebody else finished. A second claim on an open one is two thinkers
    each believing they have it, which is the failure the status exists to
    make visible.

    Nothing here can stop the second thinker from reading the execution and
    calling a model anyway. What it can do is refuse to record that one
    question was taken up twice, so the disagreement ends up in the log
    rather than only in an inference bill.

    **Claiming is not a gate on answering.** A thinker that answers without
    claiming first moves the inquiry straight from open to answered, and
    that is allowed for the reason `claim_execution` allows the same: a
    claim says who has the work, and refusing the answer would lose a
    conclusion this system was told in order to enforce an ordering the log
    does not have.
    """
    if state is None:
        raise InquiryNotFoundError(command.inquiry_id)
    if state.status is not InquiryStatus.OPEN:
        raise InquiryCannotBeClaimedError(command.inquiry_id, state.status)
    return [InquiryClaimed(inquiry_id=command.inquiry_id, occurred_at=now)]


__all__ = ["decide"]
