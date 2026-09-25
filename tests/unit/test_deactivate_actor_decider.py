"""The deactivation decision, on its own.

Update-style, so the state is an input rather than something the decider
loads. Every case here is a plain call: the three states an actor can be
in from this decider's point of view, and what each produces.
"""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from keeper.access.aggregates.actor import (
    Actor,
    ActorCannotBeDeactivatedError,
    ActorDeactivated,
    ActorNotFoundError,
)
from keeper.access.features.deactivate_actor import DeactivateActor, decide

pytestmark = pytest.mark.unit

_WHEN = datetime(2026, 9, 17, 12, 0, tzinfo=UTC)


def test_deactivating_an_active_actor_emits_one_event_carrying_its_id() -> None:
    actor_id = uuid4()
    events = decide(Actor(id=actor_id, active=True), DeactivateActor(actor_id=actor_id), now=_WHEN)
    assert events == [ActorDeactivated(actor_id=actor_id, occurred_at=_WHEN)]


def test_deactivating_an_actor_that_was_never_registered_is_refused() -> None:
    actor_id = uuid4()
    with pytest.raises(ActorNotFoundError):
        decide(None, DeactivateActor(actor_id=actor_id), now=_WHEN)


def test_deactivating_an_already_inactive_actor_is_refused() -> None:
    """A repeat call is a conflict, not a silent success. See the decider."""
    actor_id = uuid4()
    with pytest.raises(ActorCannotBeDeactivatedError):
        decide(Actor(id=actor_id, active=False), DeactivateActor(actor_id=actor_id), now=_WHEN)


def test_the_refusals_are_told_apart_by_class_not_only_by_message() -> None:
    """The two refusals map to different statuses, so they cannot share a class.

    Missing is a 404 and already-off is a 409, and `classify_error_status`
    reads the class name to decide. One shared error class would collapse
    both onto whichever status that name implied.
    """
    assert not issubclass(ActorNotFoundError, ActorCannotBeDeactivatedError)
    assert not issubclass(ActorCannotBeDeactivatedError, ActorNotFoundError)


def test_the_emitted_event_takes_its_time_from_the_supplied_clock_reading() -> None:
    """Replay determinism: nothing in the decider reads a clock of its own."""
    actor_id = uuid4()
    other = datetime(2030, 1, 1, tzinfo=UTC)
    events = decide(Actor(id=actor_id, active=True), DeactivateActor(actor_id=actor_id), now=other)
    assert events[0].occurred_at == other


def test_the_decision_is_the_same_every_time_for_the_same_inputs() -> None:
    actor_id = uuid4()
    state, command = Actor(id=actor_id, active=True), DeactivateActor(actor_id=actor_id)
    assert decide(state, command, now=_WHEN) == decide(state, command, now=_WHEN)
