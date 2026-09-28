"""The question: which operations, newest first, and where do I carry on from?

`GetOperation` names the operation it wants. This one is asking which operation to name,
which a fold cannot answer: it would mean replaying every operation stream to
see which ones match.

The filter is one optional name and that is the whole of it. No schema
search, no substring match, no "operations that take an exposure time": each of
those is a real question and none has been asked yet.
"""

from dataclasses import dataclass

from keeper.execution.aggregates.operation.state import OperationName

DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 100
"""How many operations one page carries, by default and at most.

The same two numbers the run list uses, and deliberately not a second
pair. A caller paging one collection and then the other should not have
to learn that the page sizes differ.
"""


@dataclass(frozen=True)
class ListOperations:
    """Read a page of operations, newest first.

    `name` is the filter an adapter wants: it holds the name an engine
    calls a routine and needs the operation that name was written down as.

    It may match more than one. Two operations may deliberately share a name,
    so this returns however many there are rather than promising the one
    a caller hoped for, and choosing between them is the caller's to do.
    """

    name: OperationName | None = None
    limit: int = DEFAULT_PAGE_SIZE
    cursor: str | None = None

    @classmethod
    def with_name(
        cls,
        *,
        name: str | None,
        limit: int = DEFAULT_PAGE_SIZE,
        cursor: str | None = None,
    ) -> "ListOperations":
        """Build a query from the plain string a surface receives.

        The wrapping happens here rather than at each edge so both
        surfaces get one answer to what an unacceptable name is: `OperationName`
        trims and bounds it, and an over-long one is refused with the same
        error that refuses it at definition.

        There is no pairing rule to enforce, unlike the run filter, which
        takes two halves of one reference and refuses either alone. One
        optional field needs no classmethod to be safe; it has one so the
        two slices read the same way and so the wrapping is in one place.
        """
        return cls(
            name=OperationName(name) if name is not None else None,
            limit=limit,
            cursor=cursor,
        )


__all__ = ["DEFAULT_PAGE_SIZE", "MAX_PAGE_SIZE", "ListOperations"]
