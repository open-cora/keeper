"""Replay Plan events to reconstruct current state.

`evolve` applies one event. `fold` walks a whole stream from the empty
state, which is what the read path calls after loading rows.

Both are pure and total: the same events in the same order always give
the same state, on any machine, years apart. That is the property the
whole approach rests on, and it is why nothing here reads a clock, a
config value or a database.

The wildcard arm calls `assert_never`, so adding an event class to the
union without handling it here is a type error rather than a state that
silently comes back as None.
"""

from collections.abc import Sequence
from typing import assert_never

from keeper.execution.aggregates.plan.events import PlanDefined, PlanEvent
from keeper.execution.aggregates.plan.state import Plan, PlanName


def evolve(state: Plan | None, event: PlanEvent) -> Plan:
    """Apply one event to the state before it.

    The genesis arm builds the plan and ignores the prior state, which
    must be None.

    Two things happen on the way through that are easy to read past. The
    name goes back through `PlanName`, so a row whose name no longer
    passes the bound fails here rather than folding into a plan nothing
    could have written. And the schema is shallow-copied, so the dict on
    the state and the dict in the payload that built it are not the same
    object: mutating either would otherwise change the other.
    """
    match event:
        case PlanDefined(plan_id=plan_id, plan_name=plan_name, parameters_schema=parameters_schema):
            _ = state
            return Plan(
                id=plan_id,
                name=PlanName(plan_name),
                parameters_schema=dict(parameters_schema),
            )
        case _:
            assert_never(event)


def fold(events: Sequence[PlanEvent]) -> Plan | None:
    """Replay a stream from the empty state. None means no events at all.

    Takes a `Sequence` rather than a `list` so a caller holding a list of
    one concrete event type can pass it without a cast, which is most
    callers in tests.
    """
    state: Plan | None = None
    for event in events:
        state = evolve(state, event)
    return state


__all__ = ["evolve", "fold"]
