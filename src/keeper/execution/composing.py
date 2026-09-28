"""Compose the writes that dispatch one run of one operation.

A procedure and the execution that traverses it, decided together and
handed back as appends for somebody else to commit. Nothing here touches
the store.

## Why this exists at all

Advice becomes work by composing a procedure around an operation and dispatching
an execution against it, in one transaction with whatever the caller is
recording on its own stream. That transaction cannot live here, because
the thing being recorded belongs to the caller's context and this one
knows nothing of it. So the decisions stay here, where the aggregates
they are about are modelled, and only the append moves.

The first caller assembled this itself, from six of this context's names
plus two stream types and two payload renderers, and the door said so.
What it knew was not just what it wanted but how this context gets there:
that a procedure is defined and then dispatched, that dispatching needs
the procedure as a value rather than an id, that the value has to be
folded out of an event that is not stored yet, and which of the two
streams each rendering goes on. None of that is the caller's business,
and all of it would have broken the caller when it changed.

A second caller arriving is what made that worth fixing rather than
noting. Two contexts each holding the same account of how this one
composes is two places to change and one to forget.

## What the caller still supplies, and why

Two callables rather than values.

`new_id` because four ids are minted here and a decision has to be
reproducible on replay, so they arrive from the caller's port rather than
from anything this module reaches for.

`envelope` because a stored event carries an event id, a command name, a
correlation id and a principal, and every one of those is the caller's. It
is the caller's command that produced these events, so its name is the
honest one to record, and a module that stamped its own would leave the
log saying the procedure was composed by a command nobody issued.

That is also why this hands back `StreamAppend` rather than events: the
enveloping has to happen for the appends to exist, and doing it here with
the caller's own maker keeps the boundary at the right place. What this
module knows is which stream each event belongs on. What the caller knows
is who is asking.

## What it does not decide

Whether the run should happen. This composes what was asked for and
refuses only what this context's own deciders refuse: an operation whose schema
the parameters do not satisfy, a procedure with no steps, scopes that are
malformed. Whether there is budget for it, whether a proposal was already
adopted, whether anybody authorized a beamline: all of that is the
caller's, decided before this is called.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from keeper.execution.aggregates.execution import EXECUTION_STREAM_TYPE
from keeper.execution.aggregates.execution import to_payload as execution_payload
from keeper.execution.aggregates.operation import Operation
from keeper.execution.aggregates.procedure import PROCEDURE_STREAM_TYPE, RunStep
from keeper.execution.aggregates.procedure import fold as fold_procedure
from keeper.execution.aggregates.procedure import to_payload as procedure_payload
from keeper.execution.features.define_procedure import DefineProcedure, DefineProcedureContext
from keeper.execution.features.define_procedure import decide as decide_procedure
from keeper.execution.features.dispatch_execution import (
    DispatchExecution,
    DispatchExecutionContext,
)
from keeper.execution.features.dispatch_execution import decide as decide_execution
from keeper.infrastructure.ports.event_store import NewEvent, StreamAppend


@dataclass(frozen=True, slots=True)
class ComposedRun:
    """The writes that would dispatch one run, and the ids they will create.

    `appends` is in the order the streams were decided, procedure before
    execution, which is also the order a reader of the log would want them.
    The caller adds its own and commits all of them together.

    `execution_id` is what the caller hands back to whoever asked. `step_id`
    is the run inside it, which is the thing a record citing this
    run points at: a dataset is produced by one run rather than by
    a whole traversal, and so is a proposal being taken up.
    """

    execution_id: UUID
    step_id: UUID
    appends: tuple[StreamAppend, ...]


def compose_one_run(
    *,
    operation: Operation,
    parameters: Mapping[str, Any],
    beamline: str,
    scopes: tuple[str, ...],
    now: datetime,
    new_id: Callable[[], UUID],
    envelope: Callable[[str, dict[str, Any], datetime], NewEvent],
) -> ComposedRun:
    """Decide a procedure around this operation and an execution that traverses it.

    One run, named for the operation, at the beamline and over the
    scopes the caller states. Both of those are safety-bearing and neither
    is inferred: a caller that could not state them has no business
    dispatching anything, which is the rule this signature exists to make
    unavoidable.

    The procedure is folded before it is dispatched because the dispatch
    decider takes a procedure as context and the one being dispatched was
    decided a few lines earlier and is in no store yet. The evolver is pure
    and total, so the value this builds is byte for byte the state a later
    reader will fold out of the same event.

    Four ids are minted, in a fixed order, so that a caller passing a
    deterministic generator gets the same run twice. Nothing here reads a
    clock: `now` is the caller's, and both deciders stamp it.
    """
    procedure_id = new_id()
    composed_step_id = new_id()
    execution_id = new_id()
    dispatched_step_id = new_id()

    procedure_events = decide_procedure(
        None,
        DefineProcedure(
            name=operation.name.value,
            beamline=beamline,
            steps=(
                RunStep(
                    operation_id=operation.id, parameters=dict(parameters), scopes=tuple(scopes)
                ),
            ),
        ),
        context=DefineProcedureContext(operations={operation.id: operation}),
        now=now,
        new_id=procedure_id,
        step_ids=[composed_step_id],
    )
    composed = fold_procedure(procedure_events)
    if composed is None:
        msg = "defining a procedure produced no events, which its decider cannot do"
        raise RuntimeError(msg)

    execution_events = decide_execution(
        None,
        DispatchExecution(procedure_id=procedure_id),
        context=DispatchExecutionContext(procedure=composed),
        now=now,
        new_id=execution_id,
        step_ids=[dispatched_step_id],
    )

    return ComposedRun(
        execution_id=execution_id,
        step_id=dispatched_step_id,
        appends=(
            StreamAppend(
                stream_type=PROCEDURE_STREAM_TYPE,
                stream_id=procedure_id,
                expected_version=0,
                events=[
                    envelope(type(event).__name__, procedure_payload(event), event.occurred_at)
                    for event in procedure_events
                ],
            ),
            StreamAppend(
                stream_type=EXECUTION_STREAM_TYPE,
                stream_id=execution_id,
                expected_version=0,
                events=[
                    envelope(type(event).__name__, execution_payload(event), event.occurred_at)
                    for event in execution_events
                ],
            ),
        ),
    )


__all__ = ["ComposedRun", "compose_one_run"]
