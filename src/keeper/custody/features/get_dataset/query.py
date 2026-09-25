"""The question: what did a run produce, and where is it being kept?"""

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class GetDataset:
    """Read the dataset with this id.

    A frozen dataclass rather than a bare UUID parameter, so a query
    reads like the commands beside it and gains a field without changing
    every call site. There is no decider to hand it to: reading decides
    nothing, which is why this slice has a query module where the other
    has a command.
    """

    dataset_id: UUID


__all__ = ["GetDataset"]
