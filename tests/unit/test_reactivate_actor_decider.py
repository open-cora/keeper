"""The reactivation decision, on its own.

The mirror of the deactivating decider, and tested as one: the same
three states, with the active and inactive cases swapped over.
"""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from keeper.access.aggregates.actor import (
    Actor,
    ActorCannotBeReactivatedError,
    ActorNotFoundError,
    ActorReactivated,
)
from keeper.access.features.reactivate_actor import ReactivateActor, decide

pytestmark = pytest.mark.unit

_WHEN = datetime(2026, 9, 17, 12, 0, tzinfo=UTC)


def test_reactivating_an_inactive_actor_emits_one_event_carrying_its_id() -> None:
    actor_id = uuid4()
    events = decide(Actor(id=actor_id, active=False), ReactivateActor(actor_id=actor_id), now=_WHEN)
    assert events == [ActorReactivated(actor_id=actor_id, occurred_at=_WHEN)]


def test_reactivating_an_actor_that_was_never_registered_is_refused() -> None:
    with pytest.raises(ActorNotFoundError):
        decide(None, ReactivateActor(actor_id=uuid4()), now=_WHEN)


def test_reactivating_an_already_active_actor_is_refused() -> None:
    actor_id = uuid4()
    with pytest.raises(ActorCannotBeReactivatedError):
        decide(Actor(id=actor_id, active=True), ReactivateActor(actor_id=actor_id), now=_WHEN)


def test_the_two_switch_deciders_guard_opposite_states() -> None:
    """Neither decider accepts what the other one does.

    The bodies differ by a single `not`, which is the kind of edit that
    gets copied wrong. Asserting the pair rather than each alone is what
    would notice one of them being made a copy of the other.
    """
    from keeper.access.features.deactivate_actor import DeactivateActor
    from keeper.access.features.deactivate_actor import decide as deactivate

    actor_id = uuid4()
    active, inactive = Actor(id=actor_id, active=True), Actor(id=actor_id, active=False)

    assert deactivate(active, DeactivateActor(actor_id=actor_id), now=_WHEN)
    assert decide(inactive, ReactivateActor(actor_id=actor_id), now=_WHEN)
    with pytest.raises(ActorCannotBeReactivatedError):
        decide(active, ReactivateActor(actor_id=actor_id), now=_WHEN)


def test_the_emitted_event_takes_its_time_from_the_supplied_clock_reading() -> None:
    actor_id = uuid4()
    other = datetime(2030, 1, 1, tzinfo=UTC)
    events = decide(Actor(id=actor_id, active=False), ReactivateActor(actor_id=actor_id), now=other)
    assert events[0].occurred_at == other


def test_the_decision_is_the_same_every_time_for_the_same_inputs() -> None:
    actor_id = uuid4()
    state, command = Actor(id=actor_id, active=False), ReactivateActor(actor_id=actor_id)
    assert decide(state, command, now=_WHEN) == decide(state, command, now=_WHEN)
