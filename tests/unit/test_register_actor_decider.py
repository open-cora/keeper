"""The registration decision, on its own.

Pure function, so every case here is a plain call with no fixtures, no
store and no clock. The decider is handed `now` and `new_id` rather than
fetching them, which is what makes that possible and what makes replay
give the same answer years later.
"""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from keeper.access.aggregates.actor import Actor, ActorAlreadyExistsError, ActorRegistered
from keeper.access.features.register_actor import RegisterActor, decide

pytestmark = pytest.mark.unit

_WHEN = datetime(2026, 9, 17, 12, 0, tzinfo=UTC)


def test_registering_emits_one_event_carrying_the_supplied_id_and_time() -> None:
    new_id = uuid4()
    events = decide(None, RegisterActor(), now=_WHEN, new_id=new_id)
    assert events == [ActorRegistered(actor_id=new_id, occurred_at=_WHEN)]


def test_registering_against_an_existing_actor_is_refused() -> None:
    """The precondition the handler relies on, stated rather than assumed."""
    existing = Actor(id=uuid4(), active=True)
    with pytest.raises(ActorAlreadyExistsError):
        decide(existing, RegisterActor(), now=_WHEN, new_id=uuid4())


def test_the_decision_is_the_same_every_time_for_the_same_inputs() -> None:
    """Replay determinism, asserted rather than assumed from the signature."""
    new_id = uuid4()
    command = RegisterActor()
    first = decide(None, command, now=_WHEN, new_id=new_id)
    second = decide(None, command, now=_WHEN, new_id=new_id)
    assert first == second
