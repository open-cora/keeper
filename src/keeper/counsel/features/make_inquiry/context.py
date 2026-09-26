"""The sibling state this slice's decision needs, loaded before deciding.

A decider is pure: it takes values and returns events, and it never reads
from a port. This slice still has to record how many steps the execution
had when the question was put, and the execution is a different stream in a
different bounded context.

So the handler does the reading and hands the result across as plain data,
which is what keeps the decision testable without a store and replayable
without one. The shape is `MakeProposalContext`'s next door.
"""

from dataclasses import dataclass

from keeper.execution.aggregates.execution import Execution


@dataclass(frozen=True)
class MakeInquiryContext:
    """The execution this question is about, as it stands right now.

    Read at handler time, which means it can be stale by the time the append
    lands. What is taken off it cannot go stale, though: an execution's steps
    are written by its genesis and no later event adds or removes one, so
    the count this context carries is the same count it would carry a year
    later.

    Everything about the execution that CAN change is left here rather than
    copied. How far it had got when the question was asked is not recorded,
    because the question is not about that moment: what matters is what the
    thinker saw when it read, and the thinker says so when it answers.
    """

    execution: Execution


__all__ = ["MakeInquiryContext"]
