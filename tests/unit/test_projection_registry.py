"""Registration refuses the two mistakes that fail silently at runtime.

Both refusals exist because the failure they prevent is invisible. A
duplicate name means two subscribers share one bookmark row, so each keeps
advancing the other past events it never saw. An empty subscription matches
no event type, so the subscriber registers, the worker advances it forever,
and zero events are ever processed. Neither raises on its own; both look
exactly like "nothing has happened yet".
"""

from typing import Any

import pytest

from keeper.infrastructure.projection.registry import (
    DuplicateProjectionError,
    EmptySubscriptionError,
    ProjectionRegistry,
)

pytestmark = pytest.mark.unit


class _Subscriber:
    """Minimal Subscriber: a name and a subscription set is the whole contract."""

    def __init__(self, name: str, event_types: frozenset[str]) -> None:
        self.name = name
        self.subscribed_event_types = event_types

    async def apply(self, event: Any, conn: Any) -> None:
        return None


def _sub(name: str, *event_types: str) -> Any:
    return _Subscriber(name, frozenset(event_types or {"ThingRegistered"}))


def test_a_registry_starts_empty_so_the_worker_can_skip_spawning() -> None:
    registry = ProjectionRegistry()
    assert registry.is_empty()
    assert len(registry) == 0


def test_registering_two_subscribers_under_one_name_is_refused() -> None:
    registry = ProjectionRegistry()
    registry.register(_sub("thing_summary"))
    with pytest.raises(DuplicateProjectionError, match="thing_summary"):
        registry.register(_sub("thing_summary"))


def test_a_subscriber_that_subscribes_to_nothing_is_refused_at_registration() -> None:
    registry = ProjectionRegistry()
    with pytest.raises(EmptySubscriptionError, match="never matches any event"):
        registry.register(_Subscriber("never_advances", frozenset()))


def test_a_refused_registration_leaves_the_registry_unchanged() -> None:
    registry = ProjectionRegistry()
    registry.register(_sub("first"))
    with pytest.raises(EmptySubscriptionError):
        registry.register(_Subscriber("second", frozenset()))
    assert registry.names() == {"first"}


def test_the_worker_iterates_every_registered_subscriber() -> None:
    registry = ProjectionRegistry()
    registry.register(_sub("a"))
    registry.register(_sub("b"))
    assert {s.name for s in registry} == {"a", "b"}
    assert len(registry) == 2


def test_a_subscriber_is_retrievable_by_name_and_absent_names_return_none() -> None:
    registry = ProjectionRegistry()
    registry.register(_sub("a"))
    assert registry.get("a") is not None
    assert registry.get("nope") is None
