"""Execution state, its value objects, and its domain errors.

An Execution is one traversal of a procedure: the record this system opens when
it dispatches one, and how far the thing driving it got.

## What an execution is, and what became of the Run aggregate

An execution is one traversal of a procedure, and a procedure is a
routine composed here: moves and acquisitions in an order, each declaring
the devices it touches.

There used to be a Run aggregate beside it, one carrying-out of one plan,
recorded because an engine had run something and this system was told.
It is gone, and the reason is that it and an acquisition step were the
same fact written twice once this system started composing the work: a
step cites a plan and carries the parameters it was dispatched with,
which is all a run's genesis held beyond the engine's own reference for
it. That reference is on the step too, as `engine_reference`.

Most steps cause no run in any engine at all. A move drives a motor and
opens nothing, so recording an execution as a run would have lost every
step that was not an acquisition, which is most of them. That asymmetry
is why the collapse went this direction rather than the other.

## What is copied onto the record, and what is cited

An execution holds a step of its own for every step of the procedure it
was handed, and each of those carries two things: a sentence describing
what was asked for, and the id of the composed step it came from.

The sentence is copied because the record has to stay readable on its
own, and because the fold is pure and cannot load another stream to
build one. The count has to be here for the same reason: the outcomes
need somewhere to land, so the length of the list rides the genesis.

Everything else is cited rather than copied. `procedure_step_id` reaches
the whole definition, so anything asking what a step was actually asked
to do reads the plan, the parameters and the declared scopes from the
procedure instead of from whichever of them was copied across. A copy
per question would be a field, a payload key and a migration each time,
and the thing it protects against, a definition changing under a record
that already cited it, cannot happen: a procedure has one event and
nothing edits it. Changing a routine means composing another one.

The execution also cites `procedure_id`, which says where the work was
composed. That is not the same fact as the per-step reference and
neither is derivable from the other, because knowing the procedure does
not say which of its steps a given step of this traversal is.

## Three vocabularies on one record, and none of them is the others

A reader arriving here meets three sets of words for "how it is going",
and the fastest way to be confused is to meet them one at a time.

    ExecutionStatus   how far the traversal got
                      Dispatched, Claimed, Running, Ended

    StepOutcome       what the driver observed of one step
                      Done, Refused, Broken, Skipped

    EngineState       what the engine said about the run one
                      acquisition step opened
                      Running, Paused, Completed, Aborted, Failed

The first is this system's own and is new with the dispatch. The second
belongs to whatever drove the step. The third is the engine's, relayed
by whatever watches it, and it is the five states the retired Run
aggregate held, unchanged and one scale down.

They sit on different things: the status on the execution, the outcome
and the engine state on each step. The last two are two observers of one
step and are allowed to disagree, which is the section further down.

There is a fourth list, and it is a command's rather than a record's.
`EngineReport` is the six verbs a caller sends to move `EngineState`,
six against five because a start and a resume both land in `RUNNING` and
the caller says which it meant rather than this system inferring it.

## Why a step's outcome is not a status

It is derived in the fold, from which of the four step events landed,
rather than read off a payload. An outcome written onto a payload could
contradict the event it rode in on, and the fold would have to pick a
winner.

The four are not degrees of success. `DONE` means the seam returned
without raising and says nothing about whether the science worked, which
is the distinction the acquisition findings forced and the one word here
most likely to be read as more than it is. `REFUSED` is the only good
news in the set: a claim conflict stopped the step before it touched
anything. `BROKEN` means the seam raised. `SKIPPED` means the execution had
already stopped before reaching this step.

## Why a broken step keeps a class name and not a message

The exception's type is recorded and its message is not. A message from
a driver is free text of unknown provenance heading for a row nobody can
edit, which is the field most likely to end up holding a path with a
person's name in it. The type separates a motor that would not move from
a typo in an adapter, which is the distinction a reader actually needs,
and the message stays in the logs of whatever was driving.

## Why there is a status, when nothing else in this tree has one

Every other aggregate here is free of transient states, because there is
no moment where a command has arrived and its event has not: a handler
decides and appends in one call. That holds for a record of something
somebody else did. It stops holding the moment this system dispatches.

Dispatching means waiting. An execution exists from the instant it is handed
out, and nothing is driving it until something says so, which is a state
the record has to be able to be in. So `DISPATCHED` is the first genuine
transient in this tree, and it is one on purpose rather than by
oversight.

    Dispatched   the record exists and nothing has taken it up
    Claimed      something said it is driving this
    Running      at least one step has been reported
    Ended        a close was reported

Derived in the fold from which events the stream carries, so it cannot
disagree with the history behind it.

`DISPATCHED` standing for a week says nothing was ever claimed; it does
not say the dispatch failed. Telling those apart needs something watching
the clock, which is the same answer a run whose engine died gets, and it
is not another value.

## No reference of its own

An earlier shape had the driver mint a name for the execution before its first
step, because at that moment there was no handle to refer to. Under a
dispatch there is: this system creates the record first, so the execution's id
is the handle, and it is the id a driver carries into whatever it asks an
engine to run.
"""

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from keeper.shared.bounded_text import bounded_name

EXECUTION_PROCEDURE_NAME_MAX_LENGTH = 200
"""How long a procedure's name may be after trimming.

The same bound a plan name carries, because the two are the same kind of
thing: a name some other system minted for a routine, stored whole.
"""

EXECUTION_BEAMLINE_MAX_LENGTH = 100
"""How long the beamline an execution was dispatched to may be.

The same bound the procedure puts on the value this is copied from,
declared again for the reason the name bound is declared again: two
aggregates, two declarations, and nothing stopping one from moving.
"""

EXECUTION_STEP_MAX_LENGTH = 500
"""How long one step's description may be after trimming.

Longer than a name because a step describes itself rather than being
labelled: what it does, to which record, over which devices.
"""

EXECUTION_MAX_STEPS = 1000
"""How many steps one execution may hold.

A bound rather than a limit anyone is expected to reach. It is here
because the whole list rides the genesis event, so an unbounded
procedure is an unbounded row in a table nothing can edit.

A routine with more steps than this is one an engine should be running.
A conductor composes steps that each declare the devices they touch,
which is worth its cost for tens of steps and is the wrong shape for a
raster with thousands.
"""


class InvalidExecutionProcedureNameError(ValueError):
    """A procedure name was empty, whitespace-only, or over the length bound."""

    def __init__(self, value: str) -> None:
        super().__init__(
            f"Procedure name must be 1 to {EXECUTION_PROCEDURE_NAME_MAX_LENGTH} characters "
            f"after trimming (got {len(value.strip())})"
        )


class InvalidExecutionBeamlineError(ValueError):
    """A beamline was empty, whitespace-only, or over the length bound."""

    def __init__(self, value: str) -> None:
        super().__init__(
            f"Beamline must be 1 to {EXECUTION_BEAMLINE_MAX_LENGTH} characters "
            f"after trimming (got {len(value.strip())})"
        )


class InvalidExecutionStepsError(ValueError):
    """The step list was empty, too long, or held a step that was neither.

    One error for three failures because all three say the same thing to
    a caller: the list of steps sent is not one this system will store.
    The message names which of the three it was.
    """


class InvalidStepReportError(ValueError):
    """A step report carried a detail that does not belong to its outcome.

    Each outcome has exactly one shape: a done step may name the run it
    opened, a broken step names what was raised, and a refused or skipped
    step names nothing. A report carrying a cause alongside a done
    outcome is a caller that has confused two of them, and dropping the
    field quietly would lose whichever one was right.

    A `ValueError` because it says the input was never well-formed,
    rather than that a rule about existing state was broken, which is
    the split that sends this to 400 and the errors below to 404 and
    409.
    """


class EngineState(StrEnum):
    """Where the engine run an acquisition step opened has got to.

    The second of two claims about one step, and the reason they are two
    rather than one. A step's `outcome` is what the driver observed: the
    call returned, raised, or was stopped by a claim conflict before it
    touched anything. This is what the engine said about itself, relayed
    by whatever watches that engine.

    The two can disagree, and the disagreement is the point.
    a spike drove four collisions into a real scan
    and every one of them ended `exit_status: "success"`, so neither
    observer is reliable and collapsing them would make this system pick
    a winner between two claims it cannot check. A move carries None
    here, because a move opens no run for anything to watch.

    Five values, deliberately the five the retired Run aggregate held.
    It is the same engine reporting the same lifecycle, one scale down
    from a whole run to one step's run, and a reader who has learned
    those words should not have to learn a second set for them.
    """

    RUNNING = "Running"
    PAUSED = "Paused"
    COMPLETED = "Completed"
    ABORTED = "Aborted"
    FAILED = "Failed"

    @property
    def is_terminal(self) -> bool:
        """Whether the engine can say nothing further about this run."""
        return self in (EngineState.COMPLETED, EngineState.ABORTED, EngineState.FAILED)


class EngineReport(StrEnum):
    """What an engine is being reported to have done to one step's run.

    Six values where `EngineState` has five, and the extra one is the
    reason this is a separate type rather than the state reused. A resume
    puts the run back into `RUNNING`, so a caller sending the state alone
    would be saying the same word for starting a run and for carrying one
    on, and this system would have to infer which from what it already
    held. Inference is exactly what the class-per-event rule exists to
    avoid, so the caller says which.

    This is the discriminator on a command, and commands are refusable,
    which is why a value is acceptable here and not on the events it
    produces. `ReportExecutionStep` draws the same line for the same reason.
    """

    STARTED = "Started"
    PAUSED = "Paused"
    RESUMED = "Resumed"
    COMPLETED = "Completed"
    ABORTED = "Aborted"
    FAILED = "Failed"


class StepRunCannotBeReportedError(Exception):
    """An engine-state report does not follow the one before it.

    Covers the whole state machine in one class, because every failure in
    it says the same thing to a caller: the engine's account of this run
    does not line up with what this system was already told. The message
    names the step, the state it is in, and the one that was reported.

    One class rather than a conflict class per verb, which is where this
    parted company with the retired Run aggregate. A run's five
    transitions were five slices and so five errors, each named for the
    verb its caller called. This is one slice taking a discriminator, so
    the verb is a value rather than a call site, and five classes would
    be five names for one refusal nobody can tell apart by `isinstance`.

    A 409 and not a 400, which is the correction that matters to whoever
    relays these. The split `InvalidStepReportError` states is that a
    `ValueError` says the input was never well-formed and the other
    classes say a rule about existing state was broken. This is the
    second kind: the report is perfectly well-formed and disagrees with
    what the record already holds. Filed as a 400 it made every
    redelivery of a document look like a malformed request, which is the
    one failure a reporter draining a stream should expect and the one it
    must not alert on.
    """

    def __init__(self, step_id: UUID, *, holds: "EngineState | None", got: str) -> None:
        was = holds.value if holds is not None else "nothing reported yet"
        super().__init__(f"Step {step_id} has {was} from its engine, so {got} does not follow")
        self.step_id = step_id
        self.holds = holds
        self.got = got


class ExecutionStepNotFoundError(Exception):
    """A report named a step id this execution does not hold.

    Distinct from `ExecutionStepOutOfRangeError`, which is the same mistake
    made positionally. Both are 404s and both mean the caller is talking
    about a step that is not there; they stay apart because one names an
    index and the other an id, and the message a reader needs differs.
    """

    def __init__(self, execution_id: UUID, step_id: UUID) -> None:
        super().__init__(f"Execution {execution_id} holds no step {step_id}")
        self.execution_id = execution_id
        self.step_id = step_id


class ExecutionStatus(StrEnum):
    """How far an execution has got, as this system has been told.

    Values are PascalCase strings so a log line or a response body reads
    without a mapping step.

    Derived in the fold from which events the stream carries, never
    stored. A status written onto a payload could contradict the event it
    rode in on, and the fold would have to pick a winner.

    Three live and one terminal, and the split is `is_terminal` rather
    than the shape of the word. `CLAIMED` is a past participle and the
    execution has not ended, so a reader inferring the split from the
    grammar would get it wrong. `EngineState` splits the same way and
    for the same reason, where `PAUSED` is the participle that does it.
    """

    DISPATCHED = "Dispatched"
    CLAIMED = "Claimed"
    RUNNING = "Running"
    ENDED = "Ended"

    @property
    def is_terminal(self) -> bool:
        """Whether no further event can land on an execution in this status.

        Written as a positive list of the terminals rather than as the
        complement of the live ones, because "terminal" is what the
        property is called and a reader should not have to invert it.
        """
        return self is ExecutionStatus.ENDED


class ExecutionNotFoundError(Exception):
    """A command or query named an execution id with no stream behind it."""

    def __init__(self, execution_id: UUID) -> None:
        super().__init__(f"Execution {execution_id} not found")
        self.execution_id = execution_id


class ExecutionAlreadyExistsError(Exception):
    """An execution was reported against an id that already has a stream."""

    def __init__(self, execution_id: UUID) -> None:
        super().__init__(f"Execution {execution_id} already exists")
        self.execution_id = execution_id


class ExecutionAlreadyEndedError(Exception):
    """Something arrived for an execution that has already been closed.

    Raised by both the step report and the ending, which is why it names
    neither. An execution that has ended takes nothing further: the record is
    what it was when it closed, and a late step would rewrite history
    that a reader may already have acted on.
    """

    def __init__(self, execution_id: UUID) -> None:
        super().__init__(f"Execution {execution_id} has already ended")
        self.execution_id = execution_id


class ExecutionCannotBeClaimedError(Exception):
    """A claim arrived for an execution that is not waiting to be taken up.

    Refused from every status but `DISPATCHED`, and the two cases behind
    that are worth telling apart, which is why the status rides the
    error.

    A second claim on a `CLAIMED` execution is two drivers believing they own
    one traversal, which is the failure this status exists to make
    visible. Nothing here can stop the second driver from moving a motor;
    what it can do is refuse to record that the execution was taken up twice,
    so the disagreement is in the log rather than only at the beamline.

    A claim on an `ENDED` execution is late rather than contested.
    """

    def __init__(self, execution_id: UUID, status: "ExecutionStatus") -> None:
        super().__init__(f"Execution {execution_id} cannot be claimed: it is {status}")
        self.execution_id = execution_id
        self.status = status


class ExecutionStepOutOfRangeError(Exception):
    """A step was reported at an index the execution's step list does not have.

    The step list is fixed at the genesis, so this means the caller and
    the record disagree about what is being walked. Reporting it as a
    refusal rather than growing the list is deliberate: an execution whose
    steps could be appended to afterwards would have no honest answer to
    how many were never reached.
    """

    def __init__(self, execution_id: UUID, index: int, step_count: int) -> None:
        super().__init__(
            f"Execution {execution_id} has {step_count} steps, so step {index} is not one of them"
        )
        self.execution_id = execution_id
        self.index = index
        self.step_count = step_count


class ExecutionStepAlreadyReportedError(Exception):
    """A step already has an outcome, and a second one arrived for it.

    Refused rather than accepted as a correction. An outcome is what the
    driver observed at the time, and a second reading of one step is
    either a repeated send, which the idempotency wrapper is there to
    absorb, or two drivers reporting one execution, which is a fault worth
    surfacing rather than resolving by last-write-wins.
    """

    def __init__(self, execution_id: UUID, index: int) -> None:
        super().__init__(f"Step {index} of execution {execution_id} has already been reported")
        self.execution_id = execution_id
        self.index = index


class StepOutcome(StrEnum):
    """How one step of an execution ended.

    Values are PascalCase strings so a log line or a response body reads
    without a mapping step.

    Every value is terminal for its step. A step does not pause and does
    not resume: whatever drove it either returned, was refused before it
    started, raised, or was never reached.
    """

    DONE = "Done"
    REFUSED = "Refused"
    BROKEN = "Broken"
    SKIPPED = "Skipped"


@bounded_name(
    max_length=EXECUTION_PROCEDURE_NAME_MAX_LENGTH,
    error_class=InvalidExecutionProcedureNameError,
)
@dataclass(frozen=True)
class ExecutionProcedureName:
    """The name the routine this execution traversed was composed under.

    Trimmed and length-bounded on construction, so the check runs both
    in the decider on the way in and in the evolver on the way back out
    of the log.

    Not a reference to anything. Nothing holds procedures, so two executions
    naming the same procedure are two records that happen to agree, and
    this system cannot say they traversed the same steps. The step list
    on each record is what can be compared.
    """

    value: str


@bounded_name(max_length=EXECUTION_BEAMLINE_MAX_LENGTH, error_class=InvalidExecutionBeamlineError)
@dataclass(frozen=True)
class ExecutionBeamline:
    """Which beamline this traversal was dispatched to.

    Copied off the procedure at dispatch, and bounded here as well as
    there for the reason the procedure name is: the two bounds are
    declared on two aggregates and nothing stops one moving.

    This is the only copy in this aggregate that exists for a query. The
    work intake reads a page of dispatched executions for one beamline,
    which is a filter over many rows, so the value has to be on the row
    rather than one reference away. A copy answering one reader's
    question about one row would be the mistake `DispatchedStep` records
    having made and undone.
    """

    value: str


@dataclass(frozen=True)
class DispatchedStep:
    """One step as the genesis fixes it: its id, what it does, what it runs.

    The id is minted at dispatch and rides the genesis payload, because
    the fold is pure: an id invented while replaying would differ on
    every replay, and a record other aggregates point at cannot move.

    A step gets an id at all so that something outside can name one.
    A dataset is produced by one acquisition, not by a whole traversal,
    and `(execution_id, index)` would be a pointer into the interior of
    another aggregate rather than a handle: it cannot be fetched, and
    checking it exists means folding the whole execution and bounds-checking
    an integer.

    `procedure_step_id` is that same reasoning carried one step further.
    Naming a step is only half of what a context outside this one needs;
    the other half is being able to ask something about it. This field is
    the whole of that answer: it names the composed step this one was
    dispatched from, so a reader reaches the plan, the parameters and the
    declared scopes rather than whichever of them somebody thought to
    copy across.

    A copy of one field would have been cheaper and is what this held
    first. It was replaced because every new question about a step would
    have meant a new field, a new payload key and a new migration, and
    because the sentence in `describes` already carries the same fact in
    a form nothing should parse.

    Never None, where the copied plan id was. A move comes from a
    composed step as surely as an acquisition does, so every step here
    has a definition to point at, and it is the definition that says
    which kind it was.

    Not the same id as `id`. That one names this traversal's step, which
    is what Custody and Counsel point at; this one names the definition,
    which is shared by every execution of the procedure. They cannot be
    collapsed, because one procedure is dispatched many times.
    """

    id: UUID
    describes: str
    procedure_step_id: UUID


def validated_steps(raw: tuple[DispatchedStep, ...]) -> tuple[DispatchedStep, ...]:
    """Trim a step list and refuse one this system will not store.

    Called on the way in by the decider and on the way out by the
    evolver, which is the same both-directions check a value object
    gives. A function rather than a value object because the thing being
    validated is the list, and a type per step would have to be unwrapped
    at every place a reader wants the text.

    The ids are not checked for uniqueness. They are minted one call
    apiece from the same generator that mints every other id here, so a
    collision would mean that generator is broken, and a check would be
    testing the chassis on every fold.
    """
    if not raw:
        msg = (
            "An execution must name at least one step, "
            "because an execution of nothing records nothing"
        )
        raise InvalidExecutionStepsError(msg)
    if len(raw) > EXECUTION_MAX_STEPS:
        msg = (
            f"An execution may hold at most {EXECUTION_MAX_STEPS} steps "
            f"and this one names {len(raw)}; "
            "a routine that long belongs to an engine rather than to a conductor"
        )
        raise InvalidExecutionStepsError(msg)
    trimmed = tuple(
        DispatchedStep(
            id=step.id,
            describes=step.describes.strip(),
            procedure_step_id=step.procedure_step_id,
        )
        for step in raw
    )
    for index, step in enumerate(trimmed):
        if not step.describes:
            msg = f"Step {index} describes nothing after trimming"
            raise InvalidExecutionStepsError(msg)
        if len(step.describes) > EXECUTION_STEP_MAX_LENGTH:
            msg = (
                f"Step {index} is {len(step.describes)} characters "
                f"and the bound is {EXECUTION_STEP_MAX_LENGTH}"
            )
            raise InvalidExecutionStepsError(msg)
    return trimmed


@dataclass(frozen=True)
class ExecutionStep:
    """One step of an execution, as the fold leaves it.

    `describes` comes from the genesis and never changes. Everything else
    is None until an outcome lands, and each field belongs to exactly one
    outcome: `engine_reference` to a step that was done and opened a run,
    `cause` to a break. A step that was refused or skipped adds nothing
    at all.

    A refusal carries no detail, and that is a boundary rather than a
    gap. Which step held the device and which scopes collided are facts
    about a ledger that lives in the driver's process, is not durable by
    its own argument, and names things this system neither mints nor
    resolves. Nothing here can act on either, so carrying them would be
    keeping a driver's working notes in an append-only table.

    `engine_reference` is what the engine calls the run this step caused,
    and it is a correlation hint rather than a key. Nothing here checks
    that such a run exists, and nothing could: whatever watches the
    engine records that run on its own schedule, so at the moment a step
    is reported the run it caused may not be recorded anywhere yet.
    `docs/reference/conducting.md` holds the argument.

    `cause` is an exception's class name, never its message. See the
    module docstring.

    `engine_state` is the other observer. Everything above it is what the
    driver saw; this is what the engine said about the run the step
    opened, relayed by whatever watches that engine. It is None on a move
    and on an acquisition nothing has reported yet, and it can disagree
    with `outcome`, which is why they are two fields.

    `procedure_step_id` is the one field here that says what the step was
    asked to do rather than how it went. It comes off the genesis with
    `describes` and never changes. See `DispatchedStep`.
    """

    id: UUID
    describes: str
    procedure_step_id: UUID
    outcome: StepOutcome | None = None
    engine_reference: str | None = None
    engine_state: EngineState | None = None
    cause: str | None = None

    @property
    def is_reported(self) -> bool:
        """Whether an outcome has landed for this step."""
        return self.outcome is not None


@dataclass(frozen=True)
class Execution:
    """One traversal of a procedure, as the fold leaves it.

    `procedure_id` is a reference to a sibling stream in this same
    context, not a copy of it. A procedure has one event and nothing
    edits it, so the reference stays true to what was dispatched.

    `beamline` is copied off the procedure too, and it is the one field
    here that exists for a query rather than for a reader. The work
    intake asks for every dispatched execution at one beamline, and a
    citation cannot be followed per row: the summary row has to be
    filterable by itself. See the module docstring.

    `procedure_name` and `steps` are copied off that procedure at
    dispatch and not read back through the reference. The fold is pure
    and cannot load another stream, so the length of the step list has to
    ride the genesis for the outcomes to have anywhere to land. Once the
    count is there the descriptions cost one string each and save every
    reader a second read.

    `steps` is index-aligned with the list the genesis carried, and stays
    the same length for the life of the stream.

    `status` is the only field the fold computes rather than copies. See
    the module docstring for why it is derived from the event type and
    not read off a payload.
    """

    id: UUID
    procedure_id: UUID
    procedure_name: ExecutionProcedureName
    beamline: ExecutionBeamline
    steps: tuple[ExecutionStep, ...]
    status: ExecutionStatus

    @property
    def ended(self) -> bool:
        """Whether a close was reported.

        Not whether every step was. An execution that stopped at its first
        failure reports the rest as skipped and then ends, so the two are
        different facts and both are readable.
        """
        return self.status.is_terminal

    @property
    def step_count(self) -> int:
        """How many steps the execution was asked to perform."""
        return len(self.steps)

    @property
    def reported_count(self) -> int:
        """How many steps have an outcome.

        Short of `step_count` on an execution still in flight, and short of it
        on one that ended without reporting the rest, which is what a
        record left behind by a driver that died looks like.
        """
        return sum(1 for step in self.steps if step.is_reported)


__all__ = [
    "EXECUTION_BEAMLINE_MAX_LENGTH",
    "EXECUTION_MAX_STEPS",
    "EXECUTION_PROCEDURE_NAME_MAX_LENGTH",
    "EXECUTION_STEP_MAX_LENGTH",
    "DispatchedStep",
    "Execution",
    "ExecutionAlreadyEndedError",
    "ExecutionAlreadyExistsError",
    "ExecutionBeamline",
    "ExecutionCannotBeClaimedError",
    "ExecutionNotFoundError",
    "ExecutionProcedureName",
    "ExecutionStatus",
    "ExecutionStep",
    "ExecutionStepAlreadyReportedError",
    "ExecutionStepNotFoundError",
    "ExecutionStepOutOfRangeError",
    "InvalidExecutionBeamlineError",
    "InvalidExecutionProcedureNameError",
    "InvalidExecutionStepsError",
    "InvalidStepReportError",
    "StepOutcome",
    "validated_steps",
]
