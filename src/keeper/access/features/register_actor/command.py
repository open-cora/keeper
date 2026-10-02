"""The intent: register an actor."""

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class RegisterActor:
    """Register a new actor, at an id the caller may choose.

    `actor_id` is optional and is normally left out: the handler mints
    one from its id port, and nothing about the actor is the caller's to
    decide. Replay is unaffected either way, because the id that was
    used is on the event rather than recomputed from the command.

    It exists because an actor's id has to be able to equal the id a
    caller authenticates as, and that id is not this system's to mint.
    A deployment using bearer tokens derives a principal id from the
    token's subject and publishes it in the identity provider's subject
    bindings. `PolicyAuthorize` then asks Access for an actor under that
    exact id, so without a way to say which id, the two halves can never
    meet: every grant names a principal Access has no actor for, and
    every command is refused however the policy reads.

    Registering at an id that already has a history is refused, which
    the minting path could never reach because a fresh id cannot
    collide.
    """

    actor_id: UUID | None = None


__all__ = ["RegisterActor"]
