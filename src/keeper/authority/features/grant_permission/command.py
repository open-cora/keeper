"""The intent: grant one permission under a policy."""

from dataclasses import dataclass
from uuid import UUID

from keeper.authority.aggregates.policy import Permission


@dataclass(frozen=True)
class GrantPolicyPermission:
    """Add one permission to an existing policy.

    One pair, not a set. Each grant is its own fact about who was given
    what and when, which is the question a rulebook is most often asked
    afterwards. A batch would answer it with a diff between two versions
    instead.

    The class carries the `Policy` qualifier while the slice directory
    and the MCP tool drop it. A slice name is read inside this context,
    where the surrounding path says which aggregate; this name is
    written into the event envelope, the span, the idempotency key, and,
    uniquely here, into the `command_name` of a permission inside a
    policy. A reader of the rulebook sees only the string.
    """

    policy_id: UUID
    permission: Permission


__all__ = ["GrantPolicyPermission"]
