"""The question: what does this system hold about this execution?"""

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class GetExecution:
    """Read the execution with this id, and every step it holds.

    By this system's id, not by the driver's own reference. Finding a
    execution from a reference is the other question, and a fold cannot
    answer it: it would mean replaying every execution stream to see which
    one matches. That query needs a maintained table and a slice of its
    own.

    This is the only read that returns the steps. A listing drops them,
    because they are the largest thing an execution carries and a page of
    fifty would be almost nothing else.
    """

    execution_id: UUID


__all__ = ["GetExecution"]
