"""The intent: define a plan."""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class DefinePlan:
    """Write down a runnable routine and the parameters it takes.

    Both fields are the caller's and the id is not: the new plan id, the
    timestamp and the correlation id all come from the handler's ports,
    so the decision this command produces is reproducible on replay.

    `name` is a plain string here rather than the value object the state
    holds. The decider is where it becomes one, so that the refusal of a
    bad name is listed with the slice's other refusals instead of being
    raised somewhere up at the edge by whoever built the command.
    """

    name: str
    parameters_schema: dict[str, Any]


__all__ = ["DefinePlan"]
