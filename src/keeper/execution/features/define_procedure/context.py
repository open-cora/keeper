"""The sibling state this slice's decision needs, loaded before deciding.

A decider is pure: it takes values and returns events, and it never reads
from a port. This slice has to check every acquisition's parameters
against the schema its plan declares, and each plan is a different
stream.

So the handler does the reading and hands the result across as plain
data. `dispatch_execution/context.py` next door is the same shape for
one procedure; this one carries a plan per acquisition, because a
procedure may acquire more than once.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from uuid import UUID

from keeper.execution.aggregates.plan import Plan


@dataclass(frozen=True)
class DefineProcedureContext:
    """The plans this procedure's acquisitions cite, as they stand now.

    Keyed by id and holding each distinct plan once, because a procedure
    that acquires the same plan at five sample positions should not make
    this system read the same stream five times.

    Every acquisition's plan is present. The handler refuses a procedure
    citing a plan that does not exist before building this, so the
    decider may look one up without handling a miss.

    Read at handler time, which means it can be stale by the time the
    append lands. That is accepted: the alternative is a transaction
    spanning several streams, and what this check is for is catching a
    caller who got the parameters wrong, not racing a plan being edited.
    """

    plans: Mapping[UUID, Plan]


__all__ = ["DefineProcedureContext"]
