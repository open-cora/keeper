"""The intent: take one permission back out of a policy."""

from dataclasses import dataclass
from uuid import UUID

from keeper.authority.aggregates.policy import Permission


@dataclass(frozen=True)
class RevokePolicyPermission:
    """Remove one permission from an existing policy.

    The mirror of the grant, and the same shape for the same reason. One
    pair, so each revocation is its own fact about who lost what and
    when, rather than a diff a reader has to compute between two
    versions of a set.

    ## Why there is no reason field

    A revocation is the command most likely to attract one: somebody
    will want to know why a permission went away. It is left off, and
    the absence is a decision rather than an omission.

    Free text is the shape that cannot be validated, cannot be queried,
    and ends up holding a person's name in the one table that cannot be
    edited afterwards. What a revocation was FOR is also a fact about a
    decision rather than about the policy, so the policy stream is the
    wrong home for it even when the text is well behaved.

    What the record already answers is who revoked, from which policy,
    what, and when, in the event envelope and the payload. If the
    remaining question turns out to be worth storing, it arrives as a
    closed set of values that a reader can group by, never as prose.
    """

    policy_id: UUID
    permission: Permission


__all__ = ["RevokePolicyPermission"]
