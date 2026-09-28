"""The intent: turn the loop once, by asking about one execution."""

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class OpenPursuitRound:
    """Ask a thinker what should run next, given what this execution did.

    Two fields, and the second is the only thing a caller decides. The
    question is the pursuit's goal, unchanged every round, so there is
    nothing here to phrase: a caller that could word the question would be
    able to ask something the person who authorized the pursuit did not.

    `execution_id` is what the round observes. It is also the retry guard,
    because a pursuit refuses a second round about an execution it has
    already asked about. That is what lets the thing driving a pursuit
    crash, restart and try again without opening two rounds, and it is why
    nothing has to claim a pursuit.

    The execution need not have ended. An inquiry records how much of one
    the thinker actually saw, so a question put part way through comes back
    with an answer that says so. Refusing here would enforce at the record
    what the reader can already see.

    **There is no `occurred_at`.** Asking is a speech act performed here,
    the way `make_inquiry` is, and the record this writes is the asking
    rather than a report of one. R8, makes side.

    The round index and the inquiry id are not the caller's. One is where
    the pursuit had got to and the other comes from the handler's ports.
    """

    pursuit_id: UUID
    execution_id: UUID


__all__ = ["OpenPursuitRound"]
