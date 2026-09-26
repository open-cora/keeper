"""The decision: what making an inquiry produces.

Pure. No awaits, no ports, no clock. `now` and `new_id` arrive as
parameters, and the execution arrives on the context, precisely so this
function has nothing to fetch and nothing to invent.

`actor_id` arrives as a parameter rather than on the command, because it is
not the caller's to set. The handler reads it off the authenticated
principal and passes it in, which keeps the decision a function of its
inputs while leaving the caller no way to ask as somebody else.
"""

from datetime import datetime
from uuid import UUID

from keeper.counsel.aggregates.inquiry import (
    Inquiry,
    InquiryAlreadyExistsError,
    InquiryMade,
    InquiryObjective,
)
from keeper.counsel.features.make_inquiry.command import MakeInquiry
from keeper.counsel.features.make_inquiry.context import MakeInquiryContext


def decide(
    state: Inquiry | None,
    command: MakeInquiry,
    *,
    context: MakeInquiryContext,
    actor_id: UUID,
    now: datetime,
    new_id: UUID,
) -> list[InquiryMade]:
    """Decide the events produced by making an inquiry.

    Invariants:
      - State must be None, or the id already has a history
        -> InquiryAlreadyExistsError
      - The objective must be within its bound after trimming
        -> InvalidInquiryObjectiveError

    The objective goes through its value object here rather than being
    trusted from the wire, and the trimmed form is what lands on the event.
    The route declares the same bound as a Pydantic constraint, which
    refuses a long one earlier and with a better message; this is what makes
    the rule true for the MCP surface as well.

    **The execution's status is not checked, and an inquiry about one still
    walking is allowed.** A thinker can read a half-covered execution and
    its answer says how much it saw, so refusing here would enforce at the
    record what the reader can already see for themselves. What it would
    cost is the case the asking exists for: somebody watching a long
    procedure and asking, part way through, whether it is still worth
    finishing.

    That the execution exists is NOT checked here. Discovering an absence
    needs the store, and the handler has already refused an inquiry naming
    one that does not.
    """
    if state is not None:
        raise InquiryAlreadyExistsError(state.id)
    return [
        InquiryMade(
            inquiry_id=new_id,
            actor_id=actor_id,
            execution_id=command.execution_id,
            objective=InquiryObjective(command.objective).value,
            execution_step_count=len(context.execution.steps),
            occurred_at=now,
        )
    ]


__all__ = ["decide"]
