"""The intent: record that an acquisition took this proposal."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from keeper.shared.instant import normalize_occurred_at


@dataclass(frozen=True)
class TakeProposal:
    """Record that this acquisition was performed against this proposal.

    Take, not accept. Accepting says a party considered the proposal and
    said yes; nobody did. This records that a step exists that ran what
    was proposed, and whoever composed the procedure may simply have
    gone ahead. The accepted spelling is reserved for approval by a
    person, which is a different event and a prior one.

    Names three records that already exist, and creates nothing. Both
    the execution and the step, because a step is an entity inside that
    aggregate rather than a stream of its own: the root is how the step
    is found, and finding it is how it is checked.

    `occurred_at` is when the step took it, as the caller reports it,
    and a caller who omits it gets the moment the report arrived. It is
    accepted here where the sibling command in this slice's context does
    not accept one, and the two sides of that split are the whole of R8
    inside one aggregate: making a proposal is an act this system
    performs, and a step was driven at a moment nothing here was present
    for.

    The caller is a messenger rather than a party to the fact, so
    nothing on this command says who sent it. The acquisition is what is
    being recorded.
    """

    proposal_id: UUID
    execution_id: UUID
    step_id: UUID
    occurred_at: datetime | None = None

    def __post_init__(self) -> None:
        """Refuse a naive timestamp and store the UTC form of an aware one.

        Frozen, so the normalised value goes back through
        `object.__setattr__`, the way the shared identifier does it.
        """
        if self.occurred_at is not None:
            object.__setattr__(self, "occurred_at", normalize_occurred_at(self.occurred_at))


__all__ = ["TakeProposal"]
