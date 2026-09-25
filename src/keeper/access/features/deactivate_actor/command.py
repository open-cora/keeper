"""The intent: switch this actor off."""

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class DeactivateActor:
    """Deactivate the actor with this id.

    Carries the id because, unlike registering, the caller is naming an
    actor that already exists rather than asking for a new one. The
    timestamp is still the handler's to supply from a port.
    """

    actor_id: UUID


__all__ = ["DeactivateActor"]
