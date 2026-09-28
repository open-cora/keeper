"""The intent: read the answer to a round, and act on what it says."""

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class ClosePursuitRound:
    """Act on the answer to this round, whatever it turns out to be.

    Two fields, and neither says what to do. The conclusion is already on
    the inquiry this round opened, so a caller that could pass one would be
    able to make a pursuit act on an answer nobody gave. What this command
    asks for is that the answer be read and applied.

    That is why there is one command here rather than four. The four things
    that can happen are not four requests: they are one request whose
    outcome the record already determines.

    `round_index` names the round, because a round has no id of its own. It
    is an element of the list one pursuit accumulates rather than a record
    anything else points at, the way a step is inside an execution.

    **There is no `occurred_at`.** Acting on an answer is performed here,
    and the moment this system acts is the moment it happened. That the
    thinker concluded earlier is the inquiry's fact and the inquiry already
    carries the moment. R8, makes side.
    """

    pursuit_id: UUID
    round_index: int


__all__ = ["ClosePursuitRound"]
