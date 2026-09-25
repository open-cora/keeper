"""The question: what is still open?

The query this bounded context exists for, and the one a fold cannot
answer. `GetProposal` names the proposal it wants; this one is asking
which proposal to name, and the only way to answer that from an event log
is to have kept a summary of it as the events arrived.

Three parameters and they are three different kinds of thing. The filter
says which proposals. The limit says how many of them. The cursor says
where the last page stopped.
"""

from dataclasses import dataclass

DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 100
"""How many proposals one page carries, by default and at most.

The same two numbers the sibling contexts use, and deliberately the same
rather than tuned: a page size is a property of the surface rather than
of what is on the page, and a caller paging three lists should not have
to learn three conventions.
"""


@dataclass(frozen=True)
class ListProposals:
    """Read a page of proposals, newest first.

    `is_open` narrows to proposals no run has taken, which is the whole
    reason this slice exists. False narrows to the ones a run took, and
    None, the default, asks for every proposal.

    Three states from a nullable boolean rather than two slices or a
    string. A caller that wants everything should not have to know a
    third word for it, and a query parameter absent from a URL is the
    ordinary spelling of "do not narrow on this".

    The filter is the only one. Narrowing by proposer, by plan or by date
    is each a parameter and an index, and none has a caller: an agent
    holds the ids of its own proposals, and an operator asking what
    nobody acted on is asking exactly what this answers.
    """

    is_open: bool | None = None
    limit: int = DEFAULT_PAGE_SIZE
    cursor: str | None = None


__all__ = ["DEFAULT_PAGE_SIZE", "MAX_PAGE_SIZE", "ListProposals"]
