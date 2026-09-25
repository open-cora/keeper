"""The question: which procedures, newest first, and where do I carry on from?

`GetProcedure` names the procedure it wants. This one is asking which
procedure to name, which a fold cannot answer: it would mean replaying
every procedure stream to see which ones match.

The filter is one optional name and that is the whole of it. No search
over which plans a procedure acquires and no search over which devices it
touches: both are real questions, both would need a column nothing has
built, and neither has been asked yet.
"""

from dataclasses import dataclass

from keeper.execution.aggregates.procedure.state import ProcedureName

DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 100
"""How many procedures one page carries, by default and at most.

The same two numbers the plan and run lists use, and deliberately not a
third pair. A caller paging one collection and then another should not
have to learn that the page sizes differ.
"""


@dataclass(frozen=True)
class ListProcedures:
    """Read a page of procedures, newest first.

    `name` may match more than one. Two procedures may share a name, so
    this returns however many there are rather than promising the one a
    caller hoped for, and choosing between them is the caller's to do.
    """

    name: ProcedureName | None = None
    limit: int = DEFAULT_PAGE_SIZE
    cursor: str | None = None

    @classmethod
    def with_name(
        cls,
        *,
        name: str | None,
        limit: int = DEFAULT_PAGE_SIZE,
        cursor: str | None = None,
    ) -> "ListProcedures":
        """Build a query from the plain string a surface receives.

        The wrapping happens here rather than at each edge so both
        surfaces get one answer to what an unacceptable name is:
        `ProcedureName` trims and bounds it, and an over-long one is
        refused with the same error that refuses it at definition.
        """
        return cls(
            name=ProcedureName(name) if name is not None else None,
            limit=limit,
            cursor=cursor,
        )


__all__ = ["DEFAULT_PAGE_SIZE", "MAX_PAGE_SIZE", "ListProcedures"]
