"""The Actor aggregate: its event, its replay, and its read path.

The aggregate is small enough that the interesting assertion is about
what it does NOT carry. `test_the_stored_payload_carries_only_an_id_and_a_
timestamp` is the one to keep: a field added to that payload lands in a
log that cannot be edited, and no other test in this file would notice.
"""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from keeper.access.aggregates.actor import (
    ACTOR_STREAM_TYPE,
    Actor,
    ActorDeactivated,
    ActorReactivated,
    ActorRegistered,
    evolve,
    fold,
    from_stored,
    load_actor,
    to_payload,
)
from keeper.infrastructure.adapters.in_memory_event_store import InMemoryEventStore
from keeper.infrastructure.ports.event_store import StoredEvent
from keeper.infrastructure.slices.envelope import to_new_event

pytestmark = pytest.mark.unit

_WHEN = datetime(2026, 9, 17, 12, 0, tzinfo=UTC)


def _stored(event_type: str, payload: dict[str, object]) -> StoredEvent:
    """A stored row carrying the given type and payload, envelope filled in."""
    return StoredEvent(
        position=1,
        event_id=uuid4(),
        stream_type=ACTOR_STREAM_TYPE,
        stream_id=uuid4(),
        version=1,
        event_type=event_type,
        schema_version=1,
        payload=dict(payload),
        correlation_id=uuid4(),
        causation_id=None,
        occurred_at=_WHEN,
        recorded_at=_WHEN,
    )


def test_the_stored_payload_carries_only_an_id_and_a_timestamp() -> None:
    """The payload boundary, asserted on the payload itself.

    A field added to this event would be written into a log that cannot
    be edited, and no other test in this file would notice.
    """
    actor_id = uuid4()
    payload = to_payload(ActorRegistered(actor_id=actor_id, occurred_at=_WHEN))
    assert sorted(payload) == ["actor_id", "occurred_at"]
    assert payload["actor_id"] == str(actor_id)


def test_a_registered_event_survives_a_round_trip_through_its_payload() -> None:
    original = ActorRegistered(actor_id=uuid4(), occurred_at=_WHEN)
    assert from_stored(_stored("ActorRegistered", to_payload(original))) == original


def test_from_stored_names_the_event_type_when_a_field_is_missing() -> None:
    with pytest.raises(ValueError, match="Malformed ActorRegistered payload"):
        from_stored(_stored("ActorRegistered", {"occurred_at": _WHEN.isoformat()}))


def test_from_stored_names_the_event_type_when_the_id_is_not_a_uuid() -> None:
    """A bad UUID raises ValueError, which the arm has to opt into catching."""
    with pytest.raises(ValueError, match="Malformed ActorRegistered payload"):
        from_stored(
            _stored("ActorRegistered", {"actor_id": "nope", "occurred_at": _WHEN.isoformat()})
        )


def test_from_stored_names_the_event_type_when_the_timestamp_is_unparseable() -> None:
    with pytest.raises(ValueError, match="Malformed ActorRegistered payload"):
        from_stored(_stored("ActorRegistered", {"actor_id": str(uuid4()), "occurred_at": "nope"}))


def test_from_stored_never_echoes_the_payload_into_the_error_message() -> None:
    """The message must stay safe to log even when the payload is not."""
    leaked = "someone@example.org"
    with pytest.raises(ValueError) as caught:
        from_stored(_stored("ActorRegistered", {"actor_id": leaked}))
    assert leaked not in str(caught.value)


def test_from_stored_rejects_an_event_type_this_aggregate_never_emits() -> None:
    with pytest.raises(ValueError, match="Unknown Actor event_type"):
        from_stored(_stored("ActorVanished", {}))


def test_evolve_builds_an_actor_carrying_the_registered_id() -> None:
    actor_id = uuid4()
    assert evolve(None, ActorRegistered(actor_id=actor_id, occurred_at=_WHEN)) == Actor(
        id=actor_id, active=True
    )


def test_fold_returns_none_for_a_stream_holding_no_events() -> None:
    assert fold([]) is None


def test_fold_returns_the_actor_once_the_registration_is_replayed() -> None:
    actor_id = uuid4()
    assert fold([ActorRegistered(actor_id=actor_id, occurred_at=_WHEN)]) == Actor(
        id=actor_id, active=True
    )


async def test_load_actor_returns_none_for_an_id_with_no_stream() -> None:
    assert await load_actor(InMemoryEventStore(), uuid4()) is None


async def test_load_actor_returns_the_actor_after_its_event_is_appended() -> None:
    store = InMemoryEventStore()
    actor_id = uuid4()
    await store.append(
        ACTOR_STREAM_TYPE,
        actor_id,
        0,
        [
            to_new_event(
                event_type="ActorRegistered",
                payload=to_payload(ActorRegistered(actor_id=actor_id, occurred_at=_WHEN)),
                occurred_at=_WHEN,
                event_id=uuid4(),
                command_name="RegisterActor",
                correlation_id=uuid4(),
                principal_id=actor_id,
            )
        ],
    )
    assert await load_actor(store, actor_id) == Actor(id=actor_id, active=True)


async def test_load_actor_reads_the_stream_type_the_aggregate_declares() -> None:
    """Guard the constant: a stream written under any other type is invisible."""
    store = InMemoryEventStore()
    actor_id = uuid4()
    await store.append(
        "SomethingElse",
        actor_id,
        0,
        [
            to_new_event(
                event_type="ActorRegistered",
                payload=to_payload(ActorRegistered(actor_id=actor_id, occurred_at=_WHEN)),
                occurred_at=_WHEN,
                event_id=uuid4(),
                command_name="RegisterActor",
                correlation_id=uuid4(),
                principal_id=actor_id,
            )
        ],
    )
    assert await load_actor(store, actor_id) is None


def test_the_deactivated_payload_carries_only_an_id_and_a_timestamp() -> None:
    """Same boundary as the registration payload, checked on the new event."""
    actor_id = uuid4()
    payload = to_payload(ActorDeactivated(actor_id=actor_id, occurred_at=_WHEN))
    assert sorted(payload) == ["actor_id", "occurred_at"]


def test_a_deactivated_event_survives_a_round_trip_through_its_payload() -> None:
    event = ActorDeactivated(actor_id=uuid4(), occurred_at=_WHEN)
    assert from_stored(_stored("ActorDeactivated", to_payload(event))) == event


def test_from_stored_tells_the_two_event_types_apart() -> None:
    """Both arms carry the same two fields, so only the type distinguishes them.

    A shared arm keyed on a lookup would make a typo in the mapping
    return the wrong class from a payload that parsed perfectly.
    """
    payload = to_payload(ActorDeactivated(actor_id=uuid4(), occurred_at=_WHEN))
    assert isinstance(from_stored(_stored("ActorDeactivated", payload)), ActorDeactivated)
    assert isinstance(from_stored(_stored("ActorRegistered", payload)), ActorRegistered)


def test_from_stored_names_the_deactivated_event_type_when_a_field_is_missing() -> None:
    with pytest.raises(ValueError, match="Malformed ActorDeactivated"):
        from_stored(_stored("ActorDeactivated", {"actor_id": str(uuid4())}))


def test_a_registered_actor_folds_to_active() -> None:
    actor_id = uuid4()
    assert fold([ActorRegistered(actor_id=actor_id, occurred_at=_WHEN)]) == Actor(
        id=actor_id, active=True
    )


def test_a_deactivation_folds_the_actor_to_inactive() -> None:
    actor_id = uuid4()
    state = fold(
        [
            ActorRegistered(actor_id=actor_id, occurred_at=_WHEN),
            ActorDeactivated(actor_id=actor_id, occurred_at=_WHEN),
        ]
    )
    assert state == Actor(id=actor_id, active=False)


def test_a_deactivation_keeps_the_id_it_folded_from() -> None:
    """The fold must carry the prior state forward, not rebuild from the event.

    An arm that returned `Actor(id=event.actor_id, active=False)` would
    pass the test above and would silently discard every other field the
    moment this aggregate grows one.
    """
    registered, deactivated = uuid4(), uuid4()
    state = fold(
        [
            ActorRegistered(actor_id=registered, occurred_at=_WHEN),
            ActorDeactivated(actor_id=deactivated, occurred_at=_WHEN),
        ]
    )
    assert state is not None
    assert state.id == registered


def test_evolve_refuses_a_deactivation_applied_to_an_empty_stream() -> None:
    """A transition before the genesis event means the log is corrupt."""
    with pytest.raises(ValueError, match="ActorDeactivated cannot be applied to empty state"):
        evolve(None, ActorDeactivated(actor_id=uuid4(), occurred_at=_WHEN))


def test_the_reactivated_payload_carries_only_an_id_and_a_timestamp() -> None:
    actor_id = uuid4()
    payload = to_payload(ActorReactivated(actor_id=actor_id, occurred_at=_WHEN))
    assert sorted(payload) == ["actor_id", "occurred_at"]


def test_a_reactivated_event_survives_a_round_trip_through_its_payload() -> None:
    event = ActorReactivated(actor_id=uuid4(), occurred_at=_WHEN)
    assert from_stored(_stored("ActorReactivated", to_payload(event))) == event


def test_from_stored_tells_all_three_event_types_apart() -> None:
    """Every arm carries the same two fields, so only the type distinguishes them.

    Three arms with identical bodies is exactly where a copied arm keeps
    the class it was copied from, which parses cleanly and folds wrong.
    """
    payload = to_payload(ActorReactivated(actor_id=uuid4(), occurred_at=_WHEN))
    for event_type, expected in (
        ("ActorRegistered", ActorRegistered),
        ("ActorDeactivated", ActorDeactivated),
        ("ActorReactivated", ActorReactivated),
    ):
        assert type(from_stored(_stored(event_type, payload))) is expected


def test_a_reactivation_folds_the_actor_back_to_active() -> None:
    actor_id = uuid4()
    state = fold(
        [
            ActorRegistered(actor_id=actor_id, occurred_at=_WHEN),
            ActorDeactivated(actor_id=actor_id, occurred_at=_WHEN),
            ActorReactivated(actor_id=actor_id, occurred_at=_WHEN),
        ]
    )
    assert state == Actor(id=actor_id, active=True)


def test_the_last_switch_in_the_stream_is_the_one_that_wins() -> None:
    """Replay is order-dependent, and the fold must honour the order.

    A fold that collapsed the switches into a set, or stopped at the
    first one it recognised, would agree with the test above and
    disagree here.
    """
    actor_id = uuid4()
    events = [
        ActorRegistered(actor_id=actor_id, occurred_at=_WHEN),
        ActorDeactivated(actor_id=actor_id, occurred_at=_WHEN),
        ActorReactivated(actor_id=actor_id, occurred_at=_WHEN),
        ActorDeactivated(actor_id=actor_id, occurred_at=_WHEN),
    ]
    assert fold(events) == Actor(id=actor_id, active=False)
    assert fold(events[:-1]) == Actor(id=actor_id, active=True)


def test_evolve_refuses_a_reactivation_applied_to_an_empty_stream() -> None:
    with pytest.raises(ValueError, match="ActorReactivated cannot be applied to empty state"):
        evolve(None, ActorReactivated(actor_id=uuid4(), occurred_at=_WHEN))
