"""Plan state, its name value object, and its domain errors.

A Plan is something this system can be asked to run, written down: a name
the engine knows it by, and a schema saying what parameters a
run of it must supply.

## Why a name here, when neither an actor nor a policy carries one

An actor's name labels a party that exists whether or not this system has
heard of it, so leaving it out costs nothing and keeps a person's name
out of a log that cannot be edited. A plan's name is different in kind:
it is how the engine identifies what to run, so a plan without
one names nothing and there is no act to record. Functional identity,
not decoration.

Two plans may share a name, and nothing here stops that. One routine
constrained two ways is two plans, and which one an acquisition step
cites is what says how it was constrained.

## Why the schema is required

The shared carrier-side validator accepts an absent schema and refuses
the values that would have gone with it, which is the four-cell posture
in docs/reference/conventions.md. A Plan closes that cell earlier, at
definition, by requiring a schema. An operator with nothing to constrain
declares a schema that constrains nothing and says so in the record; the
alternative is a plan that can never refuse a parameter, with nothing
saying whether that was meant.

So the absent-schema row of that table is unreachable from here. It stays
in the shared helper because the helper is shared and the next declarer
may want it.
"""

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from keeper.shared.bounded_text import bounded_name

PLAN_NAME_MAX_LENGTH = 200
"""How long a plan name may be after trimming.

Matches the bound the policy aggregate puts on a command name, which is
the nearest thing already in the tree: both are identifiers some other
system minted and this one stores whole.
"""


class InvalidPlanNameError(ValueError):
    """A plan name was empty, whitespace-only, or over the length bound.

    A `ValueError`, unlike the other errors here, because it says the
    input was never well-formed rather than that a rule about existing
    state was broken. That is the split the rejection table in
    docs/reference/patterns.md draws, and it is why this one maps to 400
    while the two below map to 404 and 409.
    """

    def __init__(self, value: str) -> None:
        super().__init__(
            f"Plan name must be 1 to {PLAN_NAME_MAX_LENGTH} characters after "
            f"trimming (got {len(value.strip())})"
        )


class InvalidPlanParametersSchemaError(ValueError):
    """The declared parameters schema is not one this system will store.

    Carries the reason the shared validator gave, which names the
    keyword or the draft that was wrong. The message is the operator's
    only guide to fixing the document they sent, so it is passed through
    rather than replaced with a generic line.
    """


class PlanNotFoundError(Exception):
    """A command or query named a plan id with no stream behind it."""

    def __init__(self, plan_id: UUID) -> None:
        super().__init__(f"Plan {plan_id} not found")
        self.plan_id = plan_id


class PlanAlreadyExistsError(Exception):
    """Definition was attempted against an id that already has a stream.

    Unreachable through the ordinary path, because a defining handler
    mints a fresh id and a fresh id has no history. It exists so the
    decider states the precondition it relies on rather than assuming it,
    and so a caller supplying its own id is refused instead of writing a
    second genesis event onto a live stream.
    """

    def __init__(self, plan_id: UUID) -> None:
        super().__init__(f"Plan {plan_id} already exists")
        self.plan_id = plan_id


@bounded_name(max_length=PLAN_NAME_MAX_LENGTH, error_class=InvalidPlanNameError)
@dataclass(frozen=True)
class PlanName:
    """The name the engine knows this routine by.

    Trimmed and length-bounded on construction. Wrapped rather than left
    a bare string so that the check runs everywhere the name enters the
    model: once in the decider, on the way in, and again in the evolver,
    on the way back out of the log.
    """

    value: str


@dataclass(frozen=True)
class Plan:
    """A runnable routine, as the fold leaves it.

    No status field. Nothing retires a plan yet, so a status would have
    one reachable value, and a one-valued field says less than no field
    while inviting a reader to believe a lifecycle is being enforced. It
    arrives with the command that flips it, the way an actor's
    availability did.
    """

    id: UUID
    name: PlanName
    parameters_schema: dict[str, Any]


__all__ = [
    "PLAN_NAME_MAX_LENGTH",
    "InvalidPlanNameError",
    "InvalidPlanParametersSchemaError",
    "Plan",
    "PlanAlreadyExistsError",
    "PlanName",
    "PlanNotFoundError",
]
