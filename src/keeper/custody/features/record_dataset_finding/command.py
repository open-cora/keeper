"""The intent: write down what somebody concluded about this data."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from keeper.custody.aggregates.dataset.finding import Finding
from keeper.shared.instant import normalize_occurred_at


@dataclass(frozen=True)
class RecordDatasetFinding:
    """Record what a computation concluded about this body of data.

    Record rather than register, which is the verb the three other
    writes on this aggregate use. Those enter a fact about the container
    into a register: where a copy is, what shapes are inside one. A
    judgement is not a fact about the container, and reusing the verb
    would quietly say that it is.

    Record rather than report, which is this system's usual word for
    writing down something that happened elsewhere. That word is already
    spent on a driver saying how a step went, and a computation saying
    what it concluded is a different act. R8 in docs/reference/naming.md
    puts both in the describes column, which is what lets a caller
    supply the moment either way.

    `finding` arrives whole rather than as a word and two loose numbers,
    for the reason every value object here does: the counts are the
    evidence for that judgement and no other, and a caller able to hand
    over the three separately is a caller able to hand over two of them.

    `occurred_at` is when the computation reached its conclusion, as the
    caller reports it, and a caller who omits it gets the moment the
    report arrived. It matters for the same reason it matters on a
    description: a finding is a statement about a moment, and the moment
    is how a later reader tells an early conclusion from one drawn after
    the data stopped changing.
    """

    dataset_id: UUID
    finding: Finding
    occurred_at: datetime | None = None

    def __post_init__(self) -> None:
        """Refuse a naive timestamp and store the UTC form of an aware one.

        Frozen, so the normalised value goes back through
        `object.__setattr__`, the way the sibling commands do it.
        """
        if self.occurred_at is not None:
            object.__setattr__(self, "occurred_at", normalize_occurred_at(self.occurred_at))


__all__ = ["RecordDatasetFinding"]
