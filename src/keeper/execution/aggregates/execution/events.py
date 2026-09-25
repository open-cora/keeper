"""Events the Execution aggregate emits, and the union its evolver dispatches on.

## The genesis is a dispatch, and that is a claim about who acted

`ExecutionDispatched` says this system handed a procedure out to be
driven. The word is the whole posture, and it is the one word this
aggregate used to get wrong: a reported record says somebody else did
something and told this system afterwards, and a dispatched one says
this system asked.

That distinction is carried by the class and not by a field. Which class
opened a stream is what says who drove the act, and a field saying so
could be set wrong. docs/bounded-contexts/execution.md draws that rule
for this context.

`ExecutionClaimed` and `ExecutionEnded` are the two that say something
about the traversal rather than about a step, and a driver sends both.
The first turns a dispatch that may be sitting unread into one that is
being acted on; the second says that driver has no more to report. Who
sent them is on the envelope, as the principal that issued the command,
so no field repeats it.

Between them they are the only pair this system does not write and no
step accounts for, which is why an execution can sit at `Dispatched`
with nothing wrong and at `Claimed` with everything wrong, and why
`ExecutionEnded` says its own absence is the load-bearing part.

## Thirteen events, and what the groups are

Counting them is the first thing a reader wants and the hardest thing to
get from a scroll, so: a genesis, a claim, four step outcomes, six
engine reports, and an ending.

    ExecutionDispatched        this system handed a procedure out
    ExecutionClaimed           something said it is driving this

    ExecutionStepDone          what the driver observed of one step
    ExecutionStepRefused
    ExecutionStepBroken
    ExecutionStepSkipped

    ExecutionStepEngineStarted    what an engine was reported to
    ExecutionStepEnginePaused     have done with one acquisition
    ExecutionStepEngineResumed    step
    ExecutionStepEngineCompleted
    ExecutionStepEngineAborted
    ExecutionStepEngineFailed

    ExecutionEnded             a close was reported

Every "four" below means the four outcome classes in the middle group,
never a count of this module.

## Why the third group says Engine and not Run

It said Run until it did not, and the word came from one acquisition
engine's document format, where a routine that is running opens a run and
gets an identifier for it. These six events relay what such an engine was
reported to have done.

Borrowing that word was wrong twice over. This system does not model a
run: it had an aggregate by that name and deleted it, precisely because a
run and an acquisition step were the same fact written twice, so a class
here named for one named something the model no longer contains. And the
word is one engine's, which is the kind of vocabulary this context
refuses everywhere else. `procedure` declines to parse a scope grammar
because the grammar belongs to whatever drives the procedure, and a
beamline is asserted rather than read out of a record prefix for the same
reason. An event class is this system's own permanent vocabulary rather
than a value passing through, so another system's noun has no business
being one. The check in `test_the_domain_names_no_product.py` is the same
rule for prose.

Engine is this context's own word for the role, and it is already load
bearing: `EngineState` is what the record holds, `EngineReport` is what a
caller sends, and `engine_state` and `engine_reference` are the fields on
a step. These six events were the only place that said otherwise.

## Why the word is not dropped altogether

The shorter names are free of any borrowed vocabulary, and they were
considered and refused:

    ExecutionStepDone          the driver: the seam returned
    ExecutionStepCompleted     the engine: the routine finished

Those two are near synonyms in English, they would sit next to each other
in one list, and they are two different observers of one step who are
allowed to disagree. A step is `Done` whenever the seam did not raise,
which says nothing about the science, and the engine may call the same
step `Failed`. Reading an events table, where the type is all there is
until somebody opens a payload, nothing would say which of the two an
event came from.

That distinction is the aggregate's own, stated in `state.py` as three
vocabularies on one record. Dropping the word keeps it true and stops the
names from carrying it.

## Four outcomes, four classes, rather than one with a word on it

A step's outcome could have ridden on a single step event as a string.
It does not, for the reason the retired Run aggregate derived its status
from the event type: a field can be set wrong and a class cannot, and
this is an append-only row nobody can go back and fix.

It also removes four nullable fields. Each class carries what its own
outcome has and nothing else: a reference to the run that was opened, or
who was holding the device, or what the seam raised. A skipped step
carries neither, which is the whole of what skipped means.

The slice that emits these is therefore out of scope for the
command-to-event derivation check, which covers slices emitting exactly
one event. `ReportExecutionStep` picks among four by what the caller
reported.

## What a broken step carries

`cause` is the class name of whatever the seam raised, never its
message. The state module gives the argument: a driver's message is free
text of unknown provenance heading for a row nobody can edit, and the
class name is what separates a motor that would not move from a typo in
an adapter.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, assert_never
from uuid import UUID

from keeper.execution.aggregates.execution.state import DispatchedStep
from keeper.infrastructure.ports.event_store import StoredEvent
from keeper.infrastructure.slices.payload import deserialize_or_raise


@dataclass(frozen=True)
class ExecutionDispatched:
    """A procedure was handed out to be driven.

    Cites the procedure and copies its name and its steps. The copy is
    not redundancy: the fold is pure and cannot load another stream, so
    the length of the step list has to be here for the outcomes to have
    anywhere to land.

    What a step copies is its rendered sentence and the plan it runs,
    which is the whole of what a step is to anything outside this
    aggregate. The procedure keeps the rest, and the record cites it.

    Carrying the whole list up front is also what makes the record
    readable after the thing driving it has gone. Steps are reported one
    at a time, so without the list a reader of an execution that stopped
    reporting would be looking at a prefix, with no way to tell an execution
    that finished early from one that was abandoned.
    """

    execution_id: UUID
    procedure_id: UUID
    procedure_name: str
    beamline: str
    steps: list[DispatchedStep]
    occurred_at: datetime


@dataclass(frozen=True)
class ExecutionClaimed:
    """Something driving said it has taken this execution up.

    No field naming what claimed it. The envelope carries the principal
    that issued the command, and a deployment runs one service account
    per beamline, so the answer is already on the row and a second copy
    could disagree with it.
    """

    execution_id: UUID
    occurred_at: datetime


@dataclass(frozen=True)
class ExecutionStepDone:
    """A step's seam returned without raising.

    Says nothing about whether the step did what it meant to. Every
    corrupted scan measured in a spike came back
    reporting success, so this is a claim this system was given rather
    than a fact it checked, and a word here meaning more would launder
    the one into the other.

    `engine_reference` is what the engine calls the run this step opened,
    for an acquisition step that opened one. None for a move, which opens
    nothing, and None for an acquisition whose engine had no name to
    give.
    """

    execution_id: UUID
    index: int
    engine_reference: str | None
    occurred_at: datetime


@dataclass(frozen=True)
class ExecutionStepRefused:
    """A claim conflict stopped a step before it touched anything.

    The only outcome in this set that is unambiguously good news:
    whatever was driving did the one thing a claim exists for.

    Which step held the device and which scopes collided are not carried.
    They belong to a ledger in the driver's process, and the argument for
    leaving them there is in `state.py`.
    """

    execution_id: UUID
    index: int
    occurred_at: datetime


@dataclass(frozen=True)
class ExecutionStepBroken:
    """A step's seam raised.

    `cause` is the exception's class name and not its message. The
    grammar is the naming rule rather than a preference: an event names
    what happened in the past participle, and the driver's own word for
    this outcome is the past tense of the same verb.
    """

    execution_id: UUID
    index: int
    cause: str
    occurred_at: datetime


@dataclass(frozen=True)
class ExecutionStepSkipped:
    """The execution had already stopped before reaching this step.

    Recorded rather than left out, so a reader sees the whole procedure
    and where it stopped. A step missing from the record and a step that
    was never reached would otherwise look identical, and only one of
    them means the driver is still alive.
    """

    execution_id: UUID
    index: int
    occurred_at: datetime


@dataclass(frozen=True)
class ExecutionEnded:
    """The execution is over, and nothing further will be reported under it.

    Says nothing about whether it finished, which the steps already say.
    An execution that stopped at its first failure ends exactly like one that
    ran every step, because ending is about the driver having no more to
    report and not about how it went.

    The absence of this event is the load-bearing part. An execution whose
    driver died has a genesis, some steps, and no ending, which is how a
    reader tells it from one still in flight only by waiting. Closing
    that gap needs something that can say the driver is gone, and nothing
    can yet.
    """

    execution_id: UUID
    occurred_at: datetime


@dataclass(frozen=True)
class ExecutionStepEngineStarted:
    """The engine began carrying out an acquisition step.

    The genesis of the second account of one step. Six classes rather
    than one carrying a state, for the reason the four outcome classes
    exist: a field can be set wrong and a class cannot, and these are
    rows nobody can go back and fix.

    `engine_reference` is what the engine calls this run. It arrives here
    as well as on `ExecutionStepDone` because the two reach this system from
    different clients on different schedules, and whichever lands first
    is the one that lets anybody find the run.
    """

    execution_id: UUID
    step_id: UUID
    engine_reference: str | None
    occurred_at: datetime


@dataclass(frozen=True)
class ExecutionStepEnginePaused:
    """The engine stopped where it was and can carry on."""

    execution_id: UUID
    step_id: UUID
    occurred_at: datetime


@dataclass(frozen=True)
class ExecutionStepEngineResumed:
    """The engine carried on from where it paused.

    The only edge on this machine that points backwards, which is what
    makes a step's engine state non-monotonic while its stream still only
    grows. Resuming is the engine saying it carried on, and a log that
    could only move forward would have no way to record that.
    """

    execution_id: UUID
    step_id: UUID
    occurred_at: datetime


@dataclass(frozen=True)
class ExecutionStepEngineCompleted:
    """The engine reached its own end.

    Says the engine reported success, and nothing about whether the
    science worked. Every corrupted scan in a spike
    ended this way.
    """

    execution_id: UUID
    step_id: UUID
    occurred_at: datetime


@dataclass(frozen=True)
class ExecutionStepEngineAborted:
    """Something outside the run stopped it."""

    execution_id: UUID
    step_id: UUID
    occurred_at: datetime


@dataclass(frozen=True)
class ExecutionStepEngineFailed:
    """The run broke.

    Carries no reason, for the reason `ExecutionStepBroken` carries a class
    name and not a message: an engine's failure text is free text of
    unknown provenance heading for a row nobody can edit.
    """

    execution_id: UUID
    step_id: UUID
    occurred_at: datetime


ExecutionEvent = (
    ExecutionDispatched
    | ExecutionClaimed
    | ExecutionStepDone
    | ExecutionStepRefused
    | ExecutionStepBroken
    | ExecutionStepSkipped
    | ExecutionStepEngineStarted
    | ExecutionStepEnginePaused
    | ExecutionStepEngineResumed
    | ExecutionStepEngineCompleted
    | ExecutionStepEngineAborted
    | ExecutionStepEngineFailed
    | ExecutionEnded
)
"""Every event that can appear on an Execution stream.

A new member is a new class added here and to this alias, never a field
bolted onto an event already in the log. Adding one without teaching the
evolver about it is a type error, because the wildcard arm there calls
`assert_never`.
"""


def to_payload(event: ExecutionEvent) -> dict[str, Any]:
    """Render an event as the primitives that get stored."""
    match event:
        case ExecutionDispatched():
            return {
                "execution_id": str(event.execution_id),
                "procedure_id": str(event.procedure_id),
                "procedure_name": event.procedure_name,
                "beamline": event.beamline,
                "steps": [
                    {
                        "id": str(step.id),
                        "describes": step.describes,
                        "procedure_step_id": str(step.procedure_step_id),
                    }
                    for step in event.steps
                ],
                "occurred_at": event.occurred_at.isoformat(),
            }
        case ExecutionClaimed():
            return {
                "execution_id": str(event.execution_id),
                "occurred_at": event.occurred_at.isoformat(),
            }
        case ExecutionStepDone():
            return {
                "execution_id": str(event.execution_id),
                "index": event.index,
                "engine_reference": event.engine_reference,
                "occurred_at": event.occurred_at.isoformat(),
            }
        case ExecutionStepRefused():
            return {
                "execution_id": str(event.execution_id),
                "index": event.index,
                "occurred_at": event.occurred_at.isoformat(),
            }
        case ExecutionStepBroken():
            return {
                "execution_id": str(event.execution_id),
                "index": event.index,
                "cause": event.cause,
                "occurred_at": event.occurred_at.isoformat(),
            }
        case ExecutionStepSkipped():
            return {
                "execution_id": str(event.execution_id),
                "index": event.index,
                "occurred_at": event.occurred_at.isoformat(),
            }
        case ExecutionStepEngineStarted():
            return {
                "execution_id": str(event.execution_id),
                "step_id": str(event.step_id),
                "engine_reference": event.engine_reference,
                "occurred_at": event.occurred_at.isoformat(),
            }
        case ExecutionStepEnginePaused():
            return {
                "execution_id": str(event.execution_id),
                "step_id": str(event.step_id),
                "occurred_at": event.occurred_at.isoformat(),
            }
        case ExecutionStepEngineResumed():
            return {
                "execution_id": str(event.execution_id),
                "step_id": str(event.step_id),
                "occurred_at": event.occurred_at.isoformat(),
            }
        case ExecutionStepEngineCompleted():
            return {
                "execution_id": str(event.execution_id),
                "step_id": str(event.step_id),
                "occurred_at": event.occurred_at.isoformat(),
            }
        case ExecutionStepEngineAborted():
            return {
                "execution_id": str(event.execution_id),
                "step_id": str(event.step_id),
                "occurred_at": event.occurred_at.isoformat(),
            }
        case ExecutionStepEngineFailed():
            return {
                "execution_id": str(event.execution_id),
                "step_id": str(event.step_id),
                "occurred_at": event.occurred_at.isoformat(),
            }
        case ExecutionEnded():
            return {
                "execution_id": str(event.execution_id),
                "occurred_at": event.occurred_at.isoformat(),
            }
        case _:
            assert_never(event)


def from_stored(stored: StoredEvent) -> ExecutionEvent:
    """Rebuild an event from its stored row.

    `extra` carries `ValueError` because the constructors below raise it
    on malformed input: a string that is not a UUID, and one that is not
    a timestamp. Without it those escape as themselves, naming the field
    rather than the event.

    The reference pair comes back as two plain strings and is not
    reassembled into a value object here. That happens in the fold, which
    is where the re-validation belongs: this function turns a row back
    into the event that was written, and the event was written with
    strings.

    The arms are spelled out one per class although two of them differ
    only in which class they build. A shared arm would have to pick the
    class by lookup, and a lookup is where a typo becomes a wrong event
    class rather than a failing branch. A skipped step folded as an
    ending would close an execution that is still running.
    """
    payload = stored.payload
    match stored.event_type:
        case "ExecutionDispatched":
            return deserialize_or_raise(
                "ExecutionDispatched",
                lambda: ExecutionDispatched(
                    execution_id=UUID(payload["execution_id"]),
                    procedure_id=UUID(payload["procedure_id"]),
                    procedure_name=payload["procedure_name"],
                    beamline=payload["beamline"],
                    steps=[
                        DispatchedStep(
                            id=UUID(raw["id"]),
                            describes=raw["describes"],
                            procedure_step_id=UUID(raw["procedure_step_id"]),
                        )
                        for raw in payload["steps"]
                    ],
                    occurred_at=datetime.fromisoformat(payload["occurred_at"]),
                ),
                extra=(ValueError,),
            )
        case "ExecutionClaimed":
            return deserialize_or_raise(
                "ExecutionClaimed",
                lambda: ExecutionClaimed(
                    execution_id=UUID(payload["execution_id"]),
                    occurred_at=datetime.fromisoformat(payload["occurred_at"]),
                ),
                extra=(ValueError,),
            )
        case "ExecutionStepDone":
            return deserialize_or_raise(
                "ExecutionStepDone",
                lambda: ExecutionStepDone(
                    execution_id=UUID(payload["execution_id"]),
                    index=payload["index"],
                    engine_reference=payload["engine_reference"],
                    occurred_at=datetime.fromisoformat(payload["occurred_at"]),
                ),
                extra=(ValueError,),
            )
        case "ExecutionStepRefused":
            return deserialize_or_raise(
                "ExecutionStepRefused",
                lambda: ExecutionStepRefused(
                    execution_id=UUID(payload["execution_id"]),
                    index=payload["index"],
                    occurred_at=datetime.fromisoformat(payload["occurred_at"]),
                ),
                extra=(ValueError,),
            )
        case "ExecutionStepBroken":
            return deserialize_or_raise(
                "ExecutionStepBroken",
                lambda: ExecutionStepBroken(
                    execution_id=UUID(payload["execution_id"]),
                    index=payload["index"],
                    cause=payload["cause"],
                    occurred_at=datetime.fromisoformat(payload["occurred_at"]),
                ),
                extra=(ValueError,),
            )
        case "ExecutionStepSkipped":
            return deserialize_or_raise(
                "ExecutionStepSkipped",
                lambda: ExecutionStepSkipped(
                    execution_id=UUID(payload["execution_id"]),
                    index=payload["index"],
                    occurred_at=datetime.fromisoformat(payload["occurred_at"]),
                ),
                extra=(ValueError,),
            )
        case "ExecutionStepEngineStarted":
            return deserialize_or_raise(
                "ExecutionStepEngineStarted",
                lambda: ExecutionStepEngineStarted(
                    execution_id=UUID(payload["execution_id"]),
                    step_id=UUID(payload["step_id"]),
                    engine_reference=payload["engine_reference"],
                    occurred_at=datetime.fromisoformat(payload["occurred_at"]),
                ),
                extra=(ValueError,),
            )
        case "ExecutionStepEnginePaused":
            return deserialize_or_raise(
                "ExecutionStepEnginePaused",
                lambda: ExecutionStepEnginePaused(
                    execution_id=UUID(payload["execution_id"]),
                    step_id=UUID(payload["step_id"]),
                    occurred_at=datetime.fromisoformat(payload["occurred_at"]),
                ),
                extra=(ValueError,),
            )
        case "ExecutionStepEngineResumed":
            return deserialize_or_raise(
                "ExecutionStepEngineResumed",
                lambda: ExecutionStepEngineResumed(
                    execution_id=UUID(payload["execution_id"]),
                    step_id=UUID(payload["step_id"]),
                    occurred_at=datetime.fromisoformat(payload["occurred_at"]),
                ),
                extra=(ValueError,),
            )
        case "ExecutionStepEngineCompleted":
            return deserialize_or_raise(
                "ExecutionStepEngineCompleted",
                lambda: ExecutionStepEngineCompleted(
                    execution_id=UUID(payload["execution_id"]),
                    step_id=UUID(payload["step_id"]),
                    occurred_at=datetime.fromisoformat(payload["occurred_at"]),
                ),
                extra=(ValueError,),
            )
        case "ExecutionStepEngineAborted":
            return deserialize_or_raise(
                "ExecutionStepEngineAborted",
                lambda: ExecutionStepEngineAborted(
                    execution_id=UUID(payload["execution_id"]),
                    step_id=UUID(payload["step_id"]),
                    occurred_at=datetime.fromisoformat(payload["occurred_at"]),
                ),
                extra=(ValueError,),
            )
        case "ExecutionStepEngineFailed":
            return deserialize_or_raise(
                "ExecutionStepEngineFailed",
                lambda: ExecutionStepEngineFailed(
                    execution_id=UUID(payload["execution_id"]),
                    step_id=UUID(payload["step_id"]),
                    occurred_at=datetime.fromisoformat(payload["occurred_at"]),
                ),
                extra=(ValueError,),
            )
        case "ExecutionEnded":
            return deserialize_or_raise(
                "ExecutionEnded",
                lambda: ExecutionEnded(
                    execution_id=UUID(payload["execution_id"]),
                    occurred_at=datetime.fromisoformat(payload["occurred_at"]),
                ),
                extra=(ValueError,),
            )
        case unknown:
            msg = f"Unknown Execution event_type: {unknown!r}"
            raise ValueError(msg)


__all__ = [
    "ExecutionClaimed",
    "ExecutionDispatched",
    "ExecutionEnded",
    "ExecutionEvent",
    "ExecutionStepBroken",
    "ExecutionStepDone",
    "ExecutionStepEngineAborted",
    "ExecutionStepEngineCompleted",
    "ExecutionStepEngineFailed",
    "ExecutionStepEnginePaused",
    "ExecutionStepEngineResumed",
    "ExecutionStepEngineStarted",
    "ExecutionStepRefused",
    "ExecutionStepSkipped",
    "from_stored",
    "to_payload",
]
