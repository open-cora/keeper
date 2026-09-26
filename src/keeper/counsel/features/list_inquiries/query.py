"""The question: what is waiting, and what has been thinking too long?

The query a fold cannot answer. `GetInquiry` names the inquiry it wants;
this one is asking which inquiry to name, and the only way to answer that
from an event log is to have kept a summary of it as the events arrived.

Three parameters and they are three different kinds of thing. The filter
says which inquiries. The limit says how many of them. The cursor says
where the last page stopped.
"""

from dataclasses import dataclass

from keeper.counsel.aggregates.inquiry import InquiryStatus

DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 100
"""How many inquiries one page carries, by default and at most.

The same two numbers the sibling listings use, and deliberately the same
rather than tuned: a page size is a property of the surface rather than of
what is on the page, and a caller paging four lists should not have to
learn four conventions.
"""


@dataclass(frozen=True)
class ListInquiries:
    """Read a page of inquiries, newest first.

    `status` narrows to one of the three the fold derives, and None, the
    default, asks for every inquiry.

    A status rather than the nullable boolean the proposal listing takes,
    and the difference is that this record has a middle. Asking for
    `CLAIMED` is asking which questions something said it was working on
    and has not come back from, which is the staleness question and is the
    one an operator asks after a thinker dies. A boolean for answered would
    fold that state in with the untouched ones and lose it.

    The filter is the only one. Narrowing by asker, by execution or by date
    is each a parameter and an index, and none has a caller yet.
    """

    status: InquiryStatus | None = None
    limit: int = DEFAULT_PAGE_SIZE
    cursor: str | None = None


__all__ = ["DEFAULT_PAGE_SIZE", "MAX_PAGE_SIZE", "ListInquiries"]
