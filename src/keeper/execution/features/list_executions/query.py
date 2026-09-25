"""The question: which executions, newest first, and where do I carry on from?

The query a fold cannot answer. `GetExecution` names the execution it wants; this
one is asking which execution to name, and the only way to answer that from
an event log is to have kept a summary of it as the events arrived.

Three parameters and they are three different kinds of thing. The filter
says which executions. The limit says how many of them. The cursor says where
the last page stopped.

No classmethod wrapping the filter, unlike the plan and procedure lists.
A procedure id is a UUID and both surfaces parse it before a query
exists, so there is nothing left for the domain to refuse.
"""

from dataclasses import dataclass
from uuid import UUID

from keeper.execution.aggregates.execution import ExecutionBeamline, ExecutionStatus

DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 100
"""How many executions one page carries, by default and at most.

A default rather than everything, because a beamline running for a year
has more executions than any caller meant to ask for. A maximum rather than
trusting the number sent, because the cost of a page is paid by the
server.
"""


@dataclass(frozen=True)
class ListExecutions:
    """Read a page of executions, newest first.

    `procedure_id` narrows to the executions dispatched for that procedure,
    which is the question this slice exists for: a routine composed once
    is walked every time it runs, so "how did this procedure go" means
    reading its executions.

    Not guaranteed to match at most one execution, and not meant to be. The
    interesting page is usually several: the same procedure run at
    different times, some ended and some not.

    `beamline` and `status` are the work intake's pair. A conductor asks
    for both, its own beamline and `Dispatched`, which is how it finds
    work nothing has taken up yet. They are separate fields rather than
    one because each answers on its own: an operator asks what 7-BM is
    doing, or what is still dispatched anywhere.

    All three narrow together. None is required, and a query with none of
    them is every execution, newest first.
    """

    procedure_id: UUID | None = None
    beamline: ExecutionBeamline | None = None
    status: ExecutionStatus | None = None
    limit: int = DEFAULT_PAGE_SIZE
    cursor: str | None = None


__all__ = ["DEFAULT_PAGE_SIZE", "MAX_PAGE_SIZE", "ListExecutions"]
