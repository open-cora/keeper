"""Registry of registered Subscribers (Projections and Reactions).

The composition root populates this during lifespan setup by calling
each BC's `register_<bc>_projections(registry, deps)`. Execution and
Custody have one; Access and Authority hold no projection and make no
call. The worker iterates the registry; the test suite uses it to drive
the `drain_projections` helper and the arch-fitness `every-registration-
has-a-table` check.

A second entry point, `register_<bc>_subscribers(registry, deps)`, is
the reaction half of the same shape and is called by nobody, because no
context has written a reaction. See docs/reference/layout.md for where
that registrar goes when one arrives.

The class is named `ProjectionRegistry` for historical reasons; it
holds any Subscriber-shaped object (Projection or Reaction). The rename
to a subscriber-centric name is still deferred, and the cost of
deferring it is no longer nothing: two contexts register projections
now, so the move is their two registrars plus this module and the
worker, where it was once this module alone.
"""

from collections.abc import Iterator

from keeper.infrastructure.projection.subscriber import Subscriber


class DuplicateProjectionError(Exception):
    """Raised when two subscribers register with the same name. Names
    must be unique because they key the bookmark row + the proj_* table
    + the arch-fitness checks."""

    def __init__(self, name: str) -> None:
        super().__init__(
            f"Subscriber with name {name!r} is already registered. "
            "Names must be unique across the whole process; they key "
            "the bookmark row and the proj_* table."
        )
        self.name = name


class EmptySubscriptionError(Exception):
    """Raised when a subscriber registers with an empty
    `subscribed_event_types` set.

    The advance query uses `event_type = ANY($subscribed)`; an empty
    set always matches zero rows, so the subscriber would silently
    never advance. Catching this at registration surfaces the bug at
    startup instead of as a "why is my subscriber empty?" investigation
    later.
    """

    def __init__(self, name: str) -> None:
        super().__init__(
            f"Subscriber {name!r} has empty subscribed_event_types. "
            "An empty set never matches any event; the subscriber would "
            "register, the worker would advance it, and zero events "
            "would ever be processed. List the event_type strings the "
            "subscriber cares about."
        )
        self.name = name


class ProjectionRegistry:
    """Holds the set of registered subscribers (Projections + Reactions);
    iterable by the worker."""

    def __init__(self) -> None:
        self._by_name: dict[str, Subscriber] = {}

    def register(self, subscriber: Subscriber) -> None:
        if subscriber.name in self._by_name:
            raise DuplicateProjectionError(subscriber.name)
        if not subscriber.subscribed_event_types:
            raise EmptySubscriptionError(subscriber.name)
        self._by_name[subscriber.name] = subscriber

    def get(self, name: str) -> Subscriber | None:
        return self._by_name.get(name)

    def names(self) -> frozenset[str]:
        return frozenset(self._by_name)

    def is_empty(self) -> bool:
        return not self._by_name

    def __iter__(self) -> Iterator[Subscriber]:
        return iter(self._by_name.values())

    def __len__(self) -> int:
        return len(self._by_name)


__all__ = ["DuplicateProjectionError", "EmptySubscriptionError", "ProjectionRegistry"]
