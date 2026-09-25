"""Actor state and its domain errors.

An Actor is a party this system has a record of: a person, a service
account, a background process. The aggregate answers one question,
whether this id names someone the system has been told about.

## Why the state is only an id

A display name is the field a reader expects here, and it is absent on
purpose. The actors this system sees are service accounts, which are
named where they are provisioned rather than here, so a name field
would be shaped now by guesswork and argued with later by its first
real caller.

Its absence is also what keeps personal data out of the record. Events
are immutable and INSERT-only at the database role level, so a name
written into a payload cannot be taken back out. Nothing in this system
holds personal data today, and writing no name is the cheapest way to
keep that true while the question of where a name would live stays open.

Availability is present, because there is now a command that flips it.
An actor is registered active and can be switched off and on again; the
record of that is the stream, and `active` is just where the fold leaves
it.
"""

from dataclasses import dataclass
from uuid import UUID


class ActorNotFoundError(Exception):
    """A command named an actor id with no stream behind it.

    Distinct from an inactive actor, which exists and is switched off.
    This one was never registered, so there is nothing to act on.
    """

    def __init__(self, actor_id: UUID) -> None:
        super().__init__(f"Actor {actor_id} not found")
        self.actor_id = actor_id


class ActorCannotBeDeactivatedError(Exception):
    """Deactivation was asked for on an actor that is already inactive.

    The 409 it becomes is declared in the Access routes module, like
    every other mapping. The name also happens to satisfy the `Cannot`
    convention `classify_error_status` applies, which matters only if a
    slice raising this is ever wrapped for idempotency; none is today.

    A no-op would have been the friendlier answer and is the wrong one.
    Two operators deactivating what they each believe to be a live actor
    should not both be told it worked.
    """

    def __init__(self, actor_id: UUID) -> None:
        super().__init__(f"Actor {actor_id} cannot be deactivated: it is already inactive")
        self.actor_id = actor_id


class ActorCannotBeReactivatedError(Exception):
    """Reactivation was asked for on an actor that is already active.

    The mirror of `ActorCannotBeDeactivatedError`, and refused for the
    same reason: a repeat call that reports success tells a caller its
    stale view of the actor was right.
    """

    def __init__(self, actor_id: UUID) -> None:
        super().__init__(f"Actor {actor_id} cannot be reactivated: it is already active")
        self.actor_id = actor_id


class ActorAlreadyExistsError(Exception):
    """Registration was attempted against an id that already has a stream.

    Unreachable through the ordinary path, because a registering handler
    mints a fresh id and a fresh id has no history. It exists so that the
    decider states the precondition it relies on rather than assuming it,
    and so a caller that supplies its own id gets a refusal instead of a
    second genesis event on a live stream.
    """

    def __init__(self, actor_id: UUID) -> None:
        super().__init__(f"Actor {actor_id} already exists")
        self.actor_id = actor_id


@dataclass(frozen=True)
class Actor:
    """An actor this system has a record of.

    Two fields. The id is its own, and `active` is where the fold leaves
    it after replaying however many switch-offs and switch-ons the stream
    holds. See the module docstring for why there is nothing else.
    """

    id: UUID
    active: bool


__all__ = [
    "Actor",
    "ActorAlreadyExistsError",
    "ActorCannotBeDeactivatedError",
    "ActorCannotBeReactivatedError",
    "ActorNotFoundError",
]
