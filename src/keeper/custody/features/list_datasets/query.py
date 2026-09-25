"""The question: what did this run produce?

The query this bounded context exists for, and the one a fold cannot
answer. `GetDataset` names the dataset it wants; this one is asking which
dataset to name, and the only way to answer that from an event log is to
have kept a summary of it as the events arrived.

Three parameters and they are three different kinds of thing. The filter
says which datasets. The limit says how many of them. The cursor says
where the last page stopped.
"""

from dataclasses import dataclass
from uuid import UUID

DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 100
"""How many datasets one page carries, by default and at most.

The same two numbers the sibling context uses, and deliberately the same
rather than tuned: a page size is a property of the surface rather than
of what is on the page, and a caller paging two lists should not have to
learn two conventions.
"""


@dataclass(frozen=True)
class ListDatasets:
    """Read a page of datasets, newest first.

    `step_id` narrows to what one run produced, which is the whole reason
    this slice exists. It is an AROC id rather than an engine's, because
    that is what the record carries and a caller holding an engine's uid
    resolves it through `GET /runs` first.

    Not guaranteed to match at most one dataset. How many datasets a run
    produces is the reporting side's policy rather than a rule here, so
    this answers with however many there are.

    There is no filter half to pair, which is the difference from the
    sibling list slice. An external reference is two strings and "exactly
    one half arrived" is a shape a surface can produce, so that query
    needs a builder and a refusal for it. A run id is one value and is
    either there or not, so this is a plain dataclass.
    """

    step_id: UUID | None = None
    limit: int = DEFAULT_PAGE_SIZE
    cursor: str | None = None


__all__ = ["DEFAULT_PAGE_SIZE", "MAX_PAGE_SIZE", "ListDatasets"]
