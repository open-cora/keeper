"""The question: what was authorized here, and is it still running?"""

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class GetPursuit:
    """Read the pursuit with this id.

    A frozen dataclass rather than a bare UUID parameter, so a query reads
    like the commands beside it and gains a field without changing every
    call site. There is no decider to hand it to: reading decides nothing,
    which is why this slice has a query module where the others have a
    command.
    """

    pursuit_id: UUID


__all__ = ["GetPursuit"]
