"""The intent: register an actor."""

from dataclasses import dataclass


@dataclass(frozen=True)
class RegisterActor:
    """Register a new actor.

    No fields. Registering mints an identity and the caller controls
    nothing about it: the new id, the timestamp and the correlation id
    are all the handler's to supply from ports, so that the decision
    made from this command is reproducible on replay.
    """


__all__ = ["RegisterActor"]
