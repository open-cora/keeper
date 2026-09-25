"""The Policy aggregate: its fold, and the round trip through storage.

The permission set is the part worth testing. It is a `frozenset` in
state and a sorted list of pairs in a payload, and those two shapes have
to mean the same thing in both directions or a policy that folds one way
today folds another way after a restart.
"""

from collections.abc import Mapping
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from keeper.authority.aggregates.policy import (
    POLICY_STREAM_TYPE,
    Permission,
    Policy,
    PolicyDefined,
    PolicyPermissionGranted,
    PolicyPermissionRevoked,
    fold,
    from_stored,
    sorted_permissions,
    to_payload,
)
from keeper.infrastructure.ports.event_store import StoredEvent

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 9, 17, 12, 0, tzinfo=UTC)


def _stored(event_type: str, payload: Mapping[str, object]) -> StoredEvent:
    return StoredEvent(
        position=1,
        event_id=uuid4(),
        stream_type=POLICY_STREAM_TYPE,
        stream_id=uuid4(),
        version=1,
        event_type=event_type,
        schema_version=1,
        payload=dict(payload),
        correlation_id=uuid4(),
        causation_id=None,
        occurred_at=_NOW,
        recorded_at=_NOW,
    )


def test_folding_an_empty_stream_gives_no_policy() -> None:
    assert fold([]) is None


def test_folding_a_definition_gives_the_permissions_it_carried() -> None:
    policy_id, alice = uuid4(), uuid4()
    granted = frozenset({Permission(principal_id=alice, command_name="DefinePolicy")})

    folded = fold([PolicyDefined(policy_id=policy_id, permissions=granted, occurred_at=_NOW)])

    assert folded == Policy(id=policy_id, permissions=granted)


def test_a_policy_with_no_permissions_folds_to_an_empty_set() -> None:
    """Permitting nothing is a state, not an absence."""
    policy_id = uuid4()
    folded = fold([PolicyDefined(policy_id=policy_id, permissions=frozenset(), occurred_at=_NOW)])
    assert folded == Policy(id=policy_id, permissions=frozenset())


def test_a_permission_set_survives_the_round_trip_through_a_payload() -> None:
    alice, bob = uuid4(), uuid4()
    original = PolicyDefined(
        policy_id=uuid4(),
        permissions=frozenset(
            {
                Permission(principal_id=alice, command_name="DefinePolicy"),
                Permission(principal_id=bob, command_name="RegisterActor"),
                Permission(principal_id=alice, command_name="RegisterActor"),
            }
        ),
        occurred_at=_NOW,
    )

    rebuilt = from_stored(_stored("PolicyDefined", to_payload(original)))

    assert rebuilt == original


def test_a_permission_set_always_serializes_in_sorted_order() -> None:
    """Determinism across processes, which one process cannot observe.

    A `Permission` hashes on a UUID and a string, and CPython randomises
    string hashing per process. A frozenset iterated without sorting
    therefore yields a different order in a different process, so two
    runs of the same deployment would write different payloads for the
    same policy, and a stored row would stop being reproducible from
    the state that produced it.

    The first version of this test built the same set twice in one
    process and compared the two payloads. They agreed however the code
    was written, because equal frozensets iterate identically within a
    process: it was the same side twice. Mutating `sorted` to `list`
    left it green.

    So this asserts the property that actually prevents the bug, over
    enough distinct sets that an implementation returning raw iteration
    order could not pass by luck.
    """
    for _ in range(50):
        permissions = frozenset(
            Permission(principal_id=uuid4(), command_name=name)
            for name in ("DefinePolicy", "RegisterActor", "GetActor", "DeactivateActor")
        )
        pairs = to_payload(PolicyDefined(uuid4(), permissions, _NOW))["permissions"]
        assert pairs == sorted(pairs)


def test_granting_the_same_pair_twice_cannot_produce_two_entries() -> None:
    """The cross-product bug is unrepresentable, not checked.

    Two pairs sharing a principal and two sharing a command must stay
    four distinct permissions, never the product of the two principals
    and the two commands.
    """
    alice, bob = uuid4(), uuid4()
    pairs = frozenset(
        {
            Permission(principal_id=alice, command_name="DefinePolicy"),
            Permission(principal_id=alice, command_name="DefinePolicy"),
            Permission(principal_id=bob, command_name="RegisterActor"),
        }
    )
    assert len(pairs) == 2


def test_an_unknown_event_type_on_a_policy_stream_is_refused() -> None:
    with pytest.raises(ValueError, match="Unknown Policy event_type"):
        from_stored(_stored("PolicyVaporised", {}))


def test_a_malformed_permission_pair_is_refused_naming_the_event() -> None:
    """A pair that does not unpack must name PolicyDefined, not the field."""
    payload = {
        "policy_id": str(uuid4()),
        "permissions": [["only-one-element"]],
        "occurred_at": _NOW.isoformat(),
    }
    with pytest.raises(Exception, match="PolicyDefined"):
        from_stored(_stored("PolicyDefined", payload))


@pytest.mark.parametrize("event_class", [PolicyPermissionGranted, PolicyPermissionRevoked])
def test_a_single_pair_event_round_trips_through_a_payload(
    event_class: type[PolicyPermissionGranted] | type[PolicyPermissionRevoked],
) -> None:
    """Both pair-carrying events, because their payloads are written twice.

    The two renderers are identical and deliberately not shared, so
    nothing but this makes them stay identical. Parametrized rather than
    written out, so the day one of them gains a field this test covers
    the other unchanged and fails on the one that moved.
    """
    original = event_class(
        policy_id=uuid4(),
        permission=Permission(principal_id=uuid4(), command_name="RegisterActor"),
        occurred_at=_NOW,
    )

    rebuilt = from_stored(_stored(event_class.__name__, to_payload(original)))

    assert rebuilt == original


def test_folding_a_definition_then_a_grant_then_a_revocation_leaves_the_survivors() -> None:
    """The whole life of a policy, replayed in order.

    Each step is a change to the set rather than a replacement of it, so
    a stream folds to the same state whatever its length. An evolver
    assigning the event's pair instead of combining it with what came
    before would pass every single-event test and fail here.
    """
    policy_id, alice, bob = uuid4(), uuid4(), uuid4()
    kept = Permission(principal_id=alice, command_name="GrantPolicyPermission")
    granted = Permission(principal_id=bob, command_name="RegisterActor")

    folded = fold(
        [
            PolicyDefined(policy_id=policy_id, permissions=frozenset({kept}), occurred_at=_NOW),
            PolicyPermissionGranted(policy_id=policy_id, permission=granted, occurred_at=_NOW),
            PolicyPermissionRevoked(policy_id=policy_id, permission=granted, occurred_at=_NOW),
        ]
    )

    assert folded == Policy(id=policy_id, permissions=frozenset({kept}))


def test_replaying_a_revocation_of_a_pair_the_policy_lost_changes_nothing() -> None:
    """The fold is total over the log, whatever the deciders refuse.

    A repeated revocation cannot reach the store, because the decider
    refuses it and the version check refuses the race. The evolver still
    has to be able to apply one: a replay that raised on a row already
    in the log would make the stream unreadable rather than report a
    problem anybody could act on.
    """
    policy_id, alice, bob = uuid4(), uuid4(), uuid4()
    kept = Permission(principal_id=alice, command_name="GrantPolicyPermission")
    gone = Permission(principal_id=bob, command_name="RegisterActor")

    folded = fold(
        [
            PolicyDefined(policy_id=policy_id, permissions=frozenset({kept}), occurred_at=_NOW),
            PolicyPermissionRevoked(policy_id=policy_id, permission=gone, occurred_at=_NOW),
            PolicyPermissionRevoked(policy_id=policy_id, permission=gone, occurred_at=_NOW),
        ]
    )

    assert folded == Policy(id=policy_id, permissions=frozenset({kept}))


def test_the_read_order_and_the_stored_order_are_the_same() -> None:
    """The reason `sorted_permissions` exists rather than three sorts.

    A payload orders pairs so a stored row is reproducible; the two read
    surfaces order them so a polling client can tell an edit from a
    reshuffle. Three call sites, one order, and three that agreed by
    coincidence would stop agreeing with nothing failing.

    Over many sets rather than one, because two orderings of a single
    small set can match by luck and CPython randomises string hashing
    per process, so the order under test is not the same twice.
    """
    for _ in range(50):
        permissions = frozenset(
            Permission(principal_id=uuid4(), command_name=name)
            for name in ("DefinePolicy", "RegisterActor", "GetActor", "DeactivateActor")
        )
        stored = to_payload(PolicyDefined(uuid4(), permissions, _NOW))["permissions"]
        assert [[str(p.principal_id), p.command_name] for p in sorted_permissions(permissions)] == (
            stored
        )
