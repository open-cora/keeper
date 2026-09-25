"""The intent: switch this actor back on."""

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class ReactivateActor:
    """Reactivate the actor with this id.

    Carries the id, like its inverse, because the caller is naming an
    actor that already exists. The timestamp is the handler's to supply
    from a port.
    """

    actor_id: UUID


__all__ = ["ReactivateActor"]
