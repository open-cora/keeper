"""Replay Procedure events to reconstruct current state.

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

from keeper.execution.aggregates.procedure.events import ProcedureDefined, ProcedureEvent
from keeper.execution.aggregates.procedure.state import (
    Procedure,
    ProcedureBeamline,
    ProcedureName,
    validated_composition,
)


def evolve(state: Procedure | None, event: ProcedureEvent) -> Procedure:
    """Apply one event to the state before it.

    The genesis arm builds the procedure and ignores the prior state,
    which must be None.

    The name, the beamline and the step list all go back through their
    checks on the way out of the log, so a row that no longer passes fails here rather
    than folding into a procedure nothing could have written. What is
    deliberately NOT re-checked is whether the plans the acquisitions
    cite still exist: that needs a store, this is pure, and a plan
    retired after the fact does not make the record of what was composed
    wrong.
    """
    match event:
        case ProcedureDefined(
            procedure_id=procedure_id,
            procedure_name=procedure_name,
            beamline=beamline,
            steps=steps,
        ):
            _ = state
            return Procedure(
                id=procedure_id,
                name=ProcedureName(procedure_name),
                beamline=ProcedureBeamline(beamline),
                steps=validated_composition(steps),
            )
        case _:
            assert_never(event)


def fold(events: Sequence[ProcedureEvent]) -> Procedure | None:
    """Replay a stream from the empty state. None means no events at all.

    Takes a `Sequence` rather than a `list` so a caller holding a list of
    one concrete event type can pass it without a cast, which is most
    callers in tests.
    """
    state: Procedure | None = None
    for event in events:
        state = evolve(state, event)
    return state


__all__ = ["evolve", "fold"]
