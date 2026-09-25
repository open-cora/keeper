"""Events the Policy aggregate emits, and the union its evolver dispatches on.

A policy is authored rather than enrolled, so its genesis is
`PolicyDefined`: nothing exists anywhere until it is written, which is
the distinction the glossary draws between Defined and Registered. The
two that follow it each carry one pair.

`to_payload` and `from_stored` are the single home for turning an event
into stored primitives and back. The granted and revoked arms render
identical payloads and are still written out separately: an or-pattern
over the two would render only the fields they share, so a field added
to one of them later would be dropped with nothing to say so.

## How a permission set is stored

In state a permission set is a `frozenset[Permission]`: deduplicated,
hashable, and O(1) to test membership, which is what the authorization
decision wants. In a payload it is a sorted list of two-element lists,
which is what JSON has and what makes two equal sets serialize
identically. Sorted, because a set has no order and an unsorted dump
would give the same policy a different payload on different runs, which
turns a stored row into something a replay cannot reproduce byte for
byte.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, assert_never
from uuid import UUID

from keeper.authority.aggregates.policy.state import Permission, sorted_permissions
from keeper.infrastructure.ports.event_store import StoredEvent
from keeper.infrastructure.slices.payload import deserialize_or_raise


@dataclass(frozen=True)
class PolicyDefined:
    """A policy was authored, with the permissions it starts out holding.

    Carries no name and no reason. The permissions are ids and command
    names, which is what keeps this payload free of anything describing
    a person, in the one table that cannot be edited afterwards.
    """

    policy_id: UUID
    permissions: frozenset[Permission]
    occurred_at: datetime


@dataclass(frozen=True)
class PolicyPermissionGranted:
    """One permission was added to a policy.

    Carries the single pair that was added, not the resulting set. The
    set is what the fold produces; the event is what happened. Writing
    the whole set on every change would make each row a snapshot, and
    two operators granting different permissions would then overwrite
    each other instead of both landing.
    """

    policy_id: UUID
    permission: Permission
    occurred_at: datetime


@dataclass(frozen=True)
class PolicyPermissionRevoked:
    """One permission was removed from a policy.

    The mirror of the grant, and stored the same way: the pair that
    left, not the set that remains. A rulebook is most often asked who
    lost what and when, and a snapshot of the survivors answers that
    only by diffing two rows.

    Carries no reason. What a revocation was FOR is a fact about a
    decision rather than about the policy, and a free-text field is the
    shape that cannot be queried, cannot be validated, and ends up
    holding a name. If the need appears it arrives as a closed set of
    values, never as prose.
    """

    policy_id: UUID
    permission: Permission
    occurred_at: datetime


PolicyEvent = PolicyDefined | PolicyPermissionGranted | PolicyPermissionRevoked
"""Every event that can appear on a Policy stream.

A new member is a new class added here and to this alias, never a field
bolted onto an event already in the log. Adding one without teaching the
evolver about it is a type error, because the wildcard arm there calls
`assert_never`.
"""


def _permissions_to_payload(permissions: frozenset[Permission]) -> list[list[str]]:
    """Render a permission set as sorted pairs. See the module docstring.

    The order comes from `sorted_permissions` rather than from sorting
    the rendered pairs, so a payload and a read surface cannot disagree
    about what order a policy is in.
    """
    return [[str(p.principal_id), p.command_name] for p in sorted_permissions(permissions)]


def _permissions_from_payload(raw: Any) -> frozenset[Permission]:
    """Rebuild a permission set from stored pairs.

    Takes `Any` because it is reading a payload, which is whatever the
    row holds rather than whatever this build expects. A malformed pair
    raises `ValueError` from the unpack or from `UUID`, and the caller
    wraps that into an error naming the event.
    """
    permissions: set[Permission] = set()
    for pair in raw:
        principal_id, command_name = pair
        permissions.add(Permission(principal_id=UUID(principal_id), command_name=command_name))
    return frozenset(permissions)


def to_payload(event: PolicyEvent) -> dict[str, Any]:
    """Render an event as the primitives that get stored."""
    match event:
        case PolicyDefined():
            return {
                "policy_id": str(event.policy_id),
                "permissions": _permissions_to_payload(event.permissions),
                "occurred_at": event.occurred_at.isoformat(),
            }
        case PolicyPermissionGranted():
            return {
                "policy_id": str(event.policy_id),
                "principal_id": str(event.permission.principal_id),
                "command_name": event.permission.command_name,
                "occurred_at": event.occurred_at.isoformat(),
            }
        case PolicyPermissionRevoked():
            return {
                "policy_id": str(event.policy_id),
                "principal_id": str(event.permission.principal_id),
                "command_name": event.permission.command_name,
                "occurred_at": event.occurred_at.isoformat(),
            }
        case _:
            assert_never(event)


def from_stored(stored: StoredEvent) -> PolicyEvent:
    """Rebuild an event from its stored row.

    `extra` carries `ValueError` because every constructor below raises
    it on malformed input: a string that is not a UUID, a string that is
    not a timestamp, and a permission pair that does not unpack into
    two. `TypeError` joins it because a payload whose `permissions` is
    not iterable, or holds something that is not a pair, fails that way
    rather than with a `ValueError`. Without both, either escapes as
    itself, naming the field rather than the event.
    """
    payload = stored.payload
    match stored.event_type:
        case "PolicyDefined":
            return deserialize_or_raise(
                "PolicyDefined",
                lambda: PolicyDefined(
                    policy_id=UUID(payload["policy_id"]),
                    permissions=_permissions_from_payload(payload["permissions"]),
                    occurred_at=datetime.fromisoformat(payload["occurred_at"]),
                ),
                extra=(ValueError, TypeError),
            )
        case "PolicyPermissionGranted":
            return deserialize_or_raise(
                "PolicyPermissionGranted",
                lambda: PolicyPermissionGranted(
                    policy_id=UUID(payload["policy_id"]),
                    permission=Permission(
                        principal_id=UUID(payload["principal_id"]),
                        command_name=payload["command_name"],
                    ),
                    occurred_at=datetime.fromisoformat(payload["occurred_at"]),
                ),
                extra=(ValueError, TypeError),
            )
        case "PolicyPermissionRevoked":
            return deserialize_or_raise(
                "PolicyPermissionRevoked",
                lambda: PolicyPermissionRevoked(
                    policy_id=UUID(payload["policy_id"]),
                    permission=Permission(
                        principal_id=UUID(payload["principal_id"]),
                        command_name=payload["command_name"],
                    ),
                    occurred_at=datetime.fromisoformat(payload["occurred_at"]),
                ),
                extra=(ValueError, TypeError),
            )
        case unknown:
            msg = f"Unknown Policy event_type: {unknown!r}"
            raise ValueError(msg)


__all__ = [
    "PolicyDefined",
    "PolicyEvent",
    "PolicyPermissionGranted",
    "PolicyPermissionRevoked",
    "from_stored",
    "to_payload",
]
