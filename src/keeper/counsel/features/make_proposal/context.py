"""The sibling state this slice's decision needs, loaded before deciding.

A decider is pure: it takes values and returns events, and it never
reads from a port. This slice still has to check the proposed values
against the schema the plan declares, and the plan is a different stream
in a different bounded context.

So the handler does the reading and hands the result across as plain
data, which is what keeps the decision testable without a store and
replayable without one. The shape is `DefineProcedureContext`'s, for the
same reason: a proposal and an acquisition step are checked against the
same schema by the same shared validator, and the only difference is
which surface refuses.
"""

from dataclasses import dataclass

from keeper.execution.aggregates.plan import Plan


@dataclass(frozen=True)
class MakeProposalContext:
    """The plan this proposal names, as it stands right now.

    Read at handler time, which means it can be stale by the time the
    append lands. That is accepted: the alternative is a transaction
    spanning two streams, and what this check is for is catching an
    agent that proposed the wrong values, not racing a plan being
    edited.

    A proposal checked against a schema that later changes is not made
    wrong by the change. It is a record of what was proposed, the way a
    run is a record of what was run.
    """

    plan: Plan


__all__ = ["MakeProposalContext"]
