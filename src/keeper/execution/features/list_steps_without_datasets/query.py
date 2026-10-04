"""The question: which runs produced data that nothing recorded where?

A run writes its output somewhere and something else has to say where.
Two programs can do that and which one does depends on what the engine
handed back: a driver holding a location files it, and a reporter
beside a store resolves a name and files that. Either can be absent,
misconfigured, or down, and when one is, the work still runs and the
data is still written.

Nothing noticed. The execution closes with every step reported `Done`,
the record is complete and correct about what happened, and the only
thing missing is any statement of where the output went. That is the
question this asks, and it cannot be asked of an execution summary,
which does not carry the steps, or of a dataset listing, which can only
show what is there.

Two parameters and they are two different kinds of thing. The filter
says whose gaps. The cursor says where the last page stopped.
"""

from dataclasses import dataclass

from keeper.execution.aggregates.execution.state import ExecutionBeamline

DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 100
"""How many steps one page carries, by default and at most.

The same two numbers every other listing here uses, and deliberately
the same rather than tuned: a page size is a property of the surface
rather than of what is on the page, and a caller paging two lists
should not have to learn two conventions.
"""


@dataclass(frozen=True)
class ListStepsWithoutDatasets:
    """Read a page of runs whose output nothing recorded, newest first.

    `beamline` narrows to one station, which is how somebody
    responsible for one asks. None spans the facility, which is how
    somebody responsible for the record asks.

    There is no filter for the opposite question. A caller wanting the
    data one run produced names the step and asks Custody, which is the
    query that context exists for, so a flag here that inverted the
    predicate would be a second route to an answer that already has
    one.

    Nothing narrows by age. The ordering is newest first and a caller
    reading until the dates stop interesting them is paging, which is a
    cursor rather than a parameter.
    """

    beamline: ExecutionBeamline | None = None
    limit: int = DEFAULT_PAGE_SIZE
    cursor: str | None = None


__all__ = ["DEFAULT_PAGE_SIZE", "MAX_PAGE_SIZE", "ListStepsWithoutDatasets"]
