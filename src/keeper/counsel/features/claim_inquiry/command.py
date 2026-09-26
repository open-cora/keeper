"""The intent: record that a thinker has taken this question up."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from keeper.shared.instant import normalize_occurred_at


@dataclass(frozen=True)
class ClaimInquiry:
    """Say that the caller is thinking about the inquiry with this id.

    Claim, and not start. Starting would say something has been concluded,
    and nothing has: this says only that a question sitting unanswered has
    been picked up. The answer is what ends the inquiry, and a thinker that
    claims one and never answers leaves a question nothing came back to,
    which is a fact worth being able to see.

    No field naming the claimant. The envelope carries the principal that
    issued the command, and a field here would be a second copy that could
    disagree.

    `occurred_at` is when the thinker took it up, as the caller reports it,
    and it is optional: a caller who omits it gets the moment the report
    arrived. Accepted for the reason `claim_execution` accepts one, because
    something picks work up on its own clock.

    **This command is optional and the record says so.** Answering an
    inquiry nobody claimed is allowed, so a thinker that was handed its
    question rather than finding it can skip this entirely. It exists for
    the other case, where something goes looking for work, and its whole
    value is that a second thinker that goes looking finds the question
    already spoken for.
    """

    inquiry_id: UUID
    occurred_at: datetime | None = None

    def __post_init__(self) -> None:
        """Refuse a naive timestamp and store the UTC form of an aware one.

        Frozen, so the normalised value goes back through
        `object.__setattr__`, the way the shared identifier does it.
        """
        if self.occurred_at is not None:
            object.__setattr__(self, "occurred_at", normalize_occurred_at(self.occurred_at))


__all__ = ["ClaimInquiry"]
