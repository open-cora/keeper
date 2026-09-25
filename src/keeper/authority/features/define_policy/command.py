"""The intent: define a policy."""

from dataclasses import dataclass

from keeper.authority.aggregates.policy import Permission


@dataclass(frozen=True)
class DefinePolicy:
    """Author a new policy, holding the permissions it starts with.

    The permissions are the caller's and the id is not: the new policy
    id, the timestamp and the correlation id all come from the handler's
    ports, so the decision this command produces is reproducible on
    replay.

    A `frozenset` rather than a list, so the command cannot express a
    duplicate and the decider has nothing to deduplicate. The route
    accepts a JSON array and converts at the edge, which is where the
    difference between what JSON has and what the domain wants belongs.
    """

    permissions: frozenset[Permission]


__all__ = ["DefinePolicy"]
