"""The intent: put a held pursuit back to work."""

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class ResumePursuit:
    """Let this pursuit open rounds again.

    One field, and for the reason withdrawing has one: there is nothing to
    say. Why it was held is on the round that held it, and why somebody
    decided it should carry on is a conversation rather than a field.

    **There is no `occurred_at`.** Resuming is a speech act performed here,
    beside starting and withdrawing. R8, makes side.
    """

    pursuit_id: UUID


__all__ = ["ResumePursuit"]
