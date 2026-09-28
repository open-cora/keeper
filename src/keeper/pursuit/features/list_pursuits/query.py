"""The question: what may dispatch work here, and what is waiting for me?

The query a fold cannot answer. `GetPursuit` names the pursuit it wants;
this one is asking which pursuit to name, and the only way to answer that
from an event log is to have kept a summary of it as the events arrived.

Four parameters and they are three different kinds of thing. Two filters
say which pursuits. The limit says how many of them. The cursor says where
the last page stopped.

Two filters where the sibling listings have one, and the extra is the
beamline. A pursuit names one in a way a proposal or an inquiry does not:
it is the authorization to run work there, so somebody standing at a
beamline needs to enumerate exactly the loops that may, without paging
through every other beamline in the facility. That is the same question
the work intake asks of executions, one context along.
"""

from dataclasses import dataclass

from keeper.pursuit.aggregates.pursuit import PursuitStatus

DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 100
"""How many pursuits one page carries, by default and at most.

The same two numbers the sibling listings use, and deliberately the same
rather than tuned: a page size is a property of the surface rather than of
what is on the page, and a caller paging five lists should not have to
learn five conventions.
"""


@dataclass(frozen=True)
class ListPursuits:
    """Read a page of pursuits, newest first.

    Both filters default to None, which asks across everything. That is the
    right default for the beamline as well as the status: a deployment with
    one beamline should not have to name it, and a person looking for a
    pursuit they half remember should not have to guess where it was.

    `cursor` continues a previous page and comes from its `next_cursor`. It
    is opaque, and a caller that takes one apart is depending on an
    ordering this is free to change.
    """

    status: PursuitStatus | None = None
    beamline: str | None = None
    limit: int = DEFAULT_PAGE_SIZE
    cursor: str | None = None


__all__ = ["DEFAULT_PAGE_SIZE", "MAX_PAGE_SIZE", "ListPursuits"]
