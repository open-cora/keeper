"""Replay Execution events to reconstruct current state.

`evolve` applies one event. `fold` walks a whole stream from the empty
state, which is what the read path calls after loading rows.

Both are pure and total: the same events in the same order always give
the same state, on any machine, years apart. Nothing here reads a clock,
a config value or a database.

The wildcard arm calls `assert_never`, so adding an event class to the
union without handling it here is a type error rather than a state that
silently comes back as None.
"""

from collections.abc import Sequence
from dataclasses import replace
from typing import assert_never
from uuid import UUID

from keeper.execution.aggregates.execution.events import (
    ExecutionClaimed,
    ExecutionDispatched,
    ExecutionEnded,
    ExecutionEvent,
    ExecutionStepBroken,
    ExecutionStepDone,
    ExecutionStepEngineAborted,
    ExecutionStepEngineCompleted,
    ExecutionStepEngineFailed,
    ExecutionStepEnginePaused,
    ExecutionStepEngineResumed,
    ExecutionStepEngineStarted,
    ExecutionStepRefused,
    ExecutionStepSkipped,
)
from keeper.execution.aggregates.execution.state import (
    EngineState,
    Execution,
    ExecutionBeamline,
    ExecutionProcedureName,
    ExecutionStatus,
    ExecutionStep,
    ExecutionStepNotFoundError,
    StepOutcome,
    validated_steps,
)
from keeper.infrastructure.slices.evolver import require_state


def _with_outcome(state: Execution, index: int, step: ExecutionStep) -> Execution:
    """Return the execution with one step replaced, leaving the rest alone.

    Out-of-range indices are refused by the decider, and a row carrying
    one would mean the genesis and a later event disagree about how many
    steps there are. Folding that into a silently shorter list would hide
    a corrupt stream, so the slice assignment is left to raise.
    """
    steps = list(state.steps)
    steps[index] = step
    return replace(state, steps=tuple(steps), status=ExecutionStatus.RUNNING)


def _with_engine_state(
    state: Execution, step_id: UUID, engine: EngineState, **extra: object
) -> Execution:
    """Return the execution with one step's engine state replaced, by id.

    By id rather than by index, which is what separates these six arms
    from the four outcome ones. A step report comes from the driver,
    which knows the position it is walking; an engine report is relayed
    by whatever watches the engine, which knows only the id the driver
    carried into the engine's own metadata.

    A step id the execution does not hold means the log is corrupt or is being
    replayed against the wrong stream, so this raises rather than folding
    into an execution that looks plausible. That is the same posture the index
    assignment above takes.

    The status moves to `RUNNING` for the reason a step report moves it:
    an engine that opened a run for one of these steps is direct evidence
    that something is driving the execution, whether or not anything claimed
    it first. `ENDED` is left alone, so a report redelivered after the
    close does not reopen it.
    """
    for index, step in enumerate(state.steps):
        if step.id != step_id:
            continue
        steps = list(state.steps)
        steps[index] = replace(step, engine_state=engine, **extra)  # pyright: ignore[reportArgumentType]
        status = state.status if state.status is ExecutionStatus.ENDED else ExecutionStatus.RUNNING
        return replace(state, steps=tuple(steps), status=status)
    raise ExecutionStepNotFoundError(state.id, step_id)


def evolve(state: Execution | None, event: ExecutionEvent) -> Execution:
    """Apply one event to the state before it.

        The genesis arm builds the execution and ignores the prior state, which
        must be None. Every other arm goes through `require_state`: a
        transition applied to an empty stream means the log is corrupt or is
        being replayed out of order, and saying so beats folding it into a
        state that looks plausible.

        This is where a step's outcome comes from. Each arm names the outcome
        its event means, so the value on state and the event that produced it
        cannot disagree; nothing reads an outcome off a payload, because no
        payload carries one.

    Two things in the genesis arm are easy to read past. The procedure name
        goes back through its value object and the step list back through
        `validated_steps`, so a row that no longer passes the bounds fails
        here rather than folding into an execution nothing could have written.

        The four step arms each replace exactly one element of `steps` and
        move the status to `RUNNING`, and touch nothing else. That the first
        step report is what makes an execution running is the one place a step
        event says something about the execution rather than only about itself,
        and it is in `_with_outcome` so all four say it the same way.

        A step report on an unclaimed execution therefore moves it straight from
        `DISPATCHED` to `RUNNING`. Claiming is what a driver does to say it
        has the work, not a gate on reporting, and a fold that refused to
        advance without it would be inventing an ordering the log does not
        have.
    """
    match event:
        case ExecutionDispatched(
            execution_id=execution_id,
            procedure_id=procedure_id,
            procedure_name=procedure_name,
            beamline=beamline,
            steps=steps,
        ):
            _ = state
            return Execution(
                id=execution_id,
                procedure_id=procedure_id,
                procedure_name=ExecutionProcedureName(value=procedure_name),
                beamline=ExecutionBeamline(value=beamline),
                steps=tuple(
                    ExecutionStep(
                        id=step.id,
                        describes=step.describes,
                        procedure_step_id=step.procedure_step_id,
                    )
                    for step in validated_steps(tuple(steps))
                ),
                status=ExecutionStatus.DISPATCHED,
            )
        case ExecutionClaimed():
            return replace(require_state(state, "ExecutionClaimed"), status=ExecutionStatus.CLAIMED)
        case ExecutionStepDone(index=index, engine_reference=engine_reference):
            live = require_state(state, "ExecutionStepDone")
            return _with_outcome(
                live,
                index,
                replace(
                    live.steps[index],
                    outcome=StepOutcome.DONE,
                    engine_reference=engine_reference,
                ),
            )
        case ExecutionStepRefused(index=index):
            live = require_state(state, "ExecutionStepRefused")
            return _with_outcome(
                live,
                index,
                replace(live.steps[index], outcome=StepOutcome.REFUSED),
            )
        case ExecutionStepBroken(index=index, cause=cause):
            live = require_state(state, "ExecutionStepBroken")
            return _with_outcome(
                live,
                index,
                replace(live.steps[index], outcome=StepOutcome.BROKEN, cause=cause),
            )
        case ExecutionStepSkipped(index=index):
            live = require_state(state, "ExecutionStepSkipped")
            return _with_outcome(
                live, index, replace(live.steps[index], outcome=StepOutcome.SKIPPED)
            )
        case ExecutionStepEngineStarted(step_id=step_id, engine_reference=engine_reference):
            return _with_engine_state(
                require_state(state, "ExecutionStepEngineStarted"),
                step_id,
                EngineState.RUNNING,
                engine_reference=engine_reference,
            )
        case ExecutionStepEnginePaused(step_id=step_id):
            return _with_engine_state(
                require_state(state, "ExecutionStepEnginePaused"), step_id, EngineState.PAUSED
            )
        case ExecutionStepEngineResumed(step_id=step_id):
            return _with_engine_state(
                require_state(state, "ExecutionStepEngineResumed"), step_id, EngineState.RUNNING
            )
        case ExecutionStepEngineCompleted(step_id=step_id):
            return _with_engine_state(
                require_state(state, "ExecutionStepEngineCompleted"), step_id, EngineState.COMPLETED
            )
        case ExecutionStepEngineAborted(step_id=step_id):
            return _with_engine_state(
                require_state(state, "ExecutionStepEngineAborted"), step_id, EngineState.ABORTED
            )
        case ExecutionStepEngineFailed(step_id=step_id):
            return _with_engine_state(
                require_state(state, "ExecutionStepEngineFailed"), step_id, EngineState.FAILED
            )
        case ExecutionEnded():
            return replace(require_state(state, "ExecutionEnded"), status=ExecutionStatus.ENDED)
        case _:
            assert_never(event)


def fold(events: Sequence[ExecutionEvent]) -> Execution | None:
    """Replay a stream from the empty state. None means no events at all.

    Takes a `Sequence` rather than a `list` so a caller holding a list of
    one concrete event type can pass it without a cast, which is most
    callers in tests.
    """
    state: Execution | None = None
    for event in events:
        state = evolve(state, event)
    return state


__all__ = ["evolve", "fold"]
