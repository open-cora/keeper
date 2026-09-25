"""Procedure state, its steps, and its domain errors.

A Procedure is a routine this system composed: an ordered list of steps,
each naming what it touches.

## What a procedure is, against what a plan is

A plan names a routine some engine already has, so its name is a handle
in that engine's vocabulary and this system holds a reference to a thing
it did not write. A procedure is authored here. Nothing anywhere holds
this sequence of moves and acquisitions until this record says so, which
is the same split between citing and composing that separates `PlanName`
from the steps below.

The two compose rather than compete. An acquisition step cites a plan,
because asking an engine to run something means naming something the
engine already knows.

## Two kinds of step, and only one of them declares what it touches

A move sends one record to one value, so what it touches is the record
it names and deriving that is exact. An acquisition hands a routine to
an engine, and nothing here can see inside the routine to work out which
devices it will drive. So an acquisition declares its scopes and a move
does not have the option, which is not an inconsistency: one is derivable
and the other is not.

An acquisition that declared nothing would be a step this system believes
touches no hardware, which is the belief that lets two of them run at
once over one motor. Declaring at least one scope is required for that
reason.

## Why scopes are stored as written

A scope is a string here and is not parsed into a namespace and a flag.
The grammar belongs to whatever drives the procedure, the overlap
arithmetic runs in that process against its own ledger, and a second
implementation of the same grammar in this tree would be two things to
keep in step for no reader's benefit. What is checked is that a scope is
a non-empty string within a bound, which is what makes it storable.

## Every step is named when it is composed

A step gets an id at definition, and the pairing lives in `ComposedStep`
rather than on the step classes themselves. That id is what an execution
cites for each of its own steps, so anything holding an execution can
reach the definition the step came from instead of reading a position
into a list nothing guarantees the shape of.

The ids come from the handler's ports, like every other id here, so the
same command replayed produces the same record.

## Definition time is where the parameters are checked

An acquisition's parameters are validated against the schema its plan
declares, and the check runs when the procedure is defined rather than
when it is walked. That is earlier and cheaper: a procedure with a
malformed acquisition is refused before anything is dispatched, instead
of failing partway through a traversal that has already moved motors.

The check reads a sibling stream, so it happens in the handler and
arrives at the decider as plain data. `define_procedure/context.py`
carries them across.
"""

import math
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from keeper.shared.bounded_text import bounded_name

PROCEDURE_NAME_MAX_LENGTH = 200
"""How long a procedure name may be after trimming.

Matches `PLAN_NAME_MAX_LENGTH`, because the two are the same kind of
thing at two scales and a reader comparing them should not find one
bound where they expected the other.
"""

PROCEDURE_BEAMLINE_MAX_LENGTH = 100
"""How long the beamline a procedure was composed for may be.

Shorter than a name, because this is an identifier rather than a
sentence: the form is the one the descriptor directories already use,
`2-bm`, and a hundred characters is generous for that.
"""

PROCEDURE_MAX_STEPS = 1000
"""How many steps one procedure may hold.

Matches the bound an execution puts on the list it is given, since an execution of a
procedure holds one step per step and the two would otherwise disagree
about what is too long.
"""

PROCEDURE_RECORD_MAX_LENGTH = 200
"""How long the record a move names may be."""

PROCEDURE_SCOPE_MAX_LENGTH = 200
"""How long one declared scope may be."""

PROCEDURE_MAX_SCOPES_PER_STEP = 100
"""How many scopes one acquisition may declare.

A bound rather than no bound, because the list rides an append-only row
and nothing else limits it. The number is generous: a tomography scan
declares a motor, a detector namespace and a shutter.
"""


class InvalidProcedureNameError(ValueError):
    """A procedure name was empty, whitespace-only, or over the bound.

    A `ValueError`, like its sibling on a plan and for the same reason:
    it says the input was never well-formed rather than that a rule about
    existing state was broken, which is the split that sends this to 400
    while the two below map to 404 and 409.
    """

    def __init__(self, value: str) -> None:
        super().__init__(
            f"Procedure name must be 1 to {PROCEDURE_NAME_MAX_LENGTH} characters after "
            f"trimming (got {len(value.strip())})"
        )


class InvalidProcedureBeamlineError(ValueError):
    """A beamline was empty, whitespace-only, or over the length bound."""

    def __init__(self, value: str) -> None:
        super().__init__(
            f"Beamline must be 1 to {PROCEDURE_BEAMLINE_MAX_LENGTH} characters after "
            f"trimming (got {len(value.strip())})"
        )


class InvalidProcedureStepsError(ValueError):
    """The step list is not one this system will store.

    Covers the list and the steps in it: an empty procedure, one over the
    length bound, a move naming no record, a move sent to a value JSON
    cannot carry, and an acquisition declaring no scopes.

    One class for all of them rather than one per shape. They arrive from
    the same field on the same command, a caller fixing any of them is
    editing the same list, and the message names which step and what was
    wrong with it.
    """


class InvalidProcedureParametersError(ValueError):
    """An acquisition's parameters do not satisfy the plan's schema.

    Carries the reason the shared validator gave, which names the field
    and the constraint it failed, and the index of the step it came from,
    because a procedure may hold several acquisitions and a caller told
    only that one of them is wrong has to check each.
    """

    def __init__(self, index: int, reason: str) -> None:
        super().__init__(f"Step {index} does not satisfy the plan it cites: {reason}")
        self.index = index
        self.reason = reason


class ProcedureNotFoundError(Exception):
    """A command or query named a procedure id with no stream behind it."""

    def __init__(self, procedure_id: UUID) -> None:
        super().__init__(f"Procedure {procedure_id} not found")
        self.procedure_id = procedure_id


class ProcedureStepNotFoundError(Exception):
    """A lookup named a step id this procedure does not hold.

    Unreachable through the ordinary path, the way
    `ProcedureAlreadyExistsError` below is. An execution's step cites a
    composed step of the procedure it was dispatched from, a procedure
    has one event and nothing edits it, so a citation that resolved once
    resolves forever.

    It exists so that the lookup states what it relies on rather than
    assuming it, and so a caller that paired an execution with the wrong
    procedure is refused instead of silently reading no step at all.
    """

    def __init__(self, procedure_id: UUID, step_id: UUID) -> None:
        super().__init__(f"Procedure {procedure_id} holds no step {step_id}")
        self.procedure_id = procedure_id
        self.step_id = step_id


class ProcedureAlreadyExistsError(Exception):
    """Definition was attempted against an id that already has a stream.

    Unreachable through the ordinary path, because a defining handler
    mints a fresh id and a fresh id has no history. It exists so the
    decider states the precondition it relies on rather than assuming it,
    and so a caller supplying its own id is refused instead of writing a
    second genesis event onto a live stream.
    """

    def __init__(self, procedure_id: UUID) -> None:
        super().__init__(f"Procedure {procedure_id} already exists")
        self.procedure_id = procedure_id


@bounded_name(max_length=PROCEDURE_NAME_MAX_LENGTH, error_class=InvalidProcedureNameError)
@dataclass(frozen=True)
class ProcedureName:
    """What this system calls the routine it composed.

    Trimmed and length-bounded on construction. Wrapped rather than left
    a bare string so the check runs everywhere the name enters the model:
    once in the decider, on the way in, and again in the evolver, on the
    way back out of the log.
    """

    value: str


@bounded_name(max_length=PROCEDURE_BEAMLINE_MAX_LENGTH, error_class=InvalidProcedureBeamlineError)
@dataclass(frozen=True)
class ProcedureBeamline:
    """Which beamline this routine was composed for.

    Trimmed and length-bounded on construction, so the check runs on the
    way in and again on the way back out of the log, the way
    `ProcedureName` does.

    Stored as written and checked against nothing, for the reason a scope
    is: there is no Beamline aggregate, and a second register of which
    beamlines exist would be a thing to keep in step with the descriptor
    directories for no reader's benefit. What is checked is that it is a
    non-empty string within a bound, which is what makes it storable.

    Required rather than optional. A procedure whose steps name `2bmb:m1`
    can only run at 2-BM, so the beamline is already determined by the
    steps; this states once what they imply. Leaving it off would mean a
    procedure nothing can route, which is a procedure nothing can drive.

    ## Why this is not derived from the steps

    It could be. A move names a record and an acquisition declares
    scopes, and both carry a prefix that says where they are. Deriving it
    would mean parsing that prefix, and the module docstring above says
    why this system does not: the grammar belongs to whatever drives the
    procedure, and a second implementation of it here would be a thing to
    keep in step. An asserted field that a composer gets wrong is a
    routing mistake somebody can see and fix. A parsed one would make
    this system's idea of a beamline depend on a convention it does not
    own.
    """

    value: str


@dataclass(frozen=True)
class MoveStep:
    """Send one record to one value.

    No declared scopes. What a move touches is the record it names, and
    the driver derives the claim from that, so a field here would be a
    second chance to say the same thing differently.
    """

    record: str
    to: float


@dataclass(frozen=True)
class AcquireStep:
    """Ask an engine to run a plan, over devices this step declares.

    `parameters` is checked against the cited plan's schema at definition
    time. What is stored is what the caller sent, not a normalised form:
    an engine fills its own defaults, and a record of what was asked for
    is more useful than a record of what some validator made of it.
    """

    plan_id: UUID
    parameters: dict[str, Any] = field(default_factory=dict[str, Any])
    scopes: tuple[str, ...] = ()


ProcedureStep = MoveStep | AcquireStep
"""What a procedure is made of.

Closed at two. A third kind is a class added here and to this alias, and
to the arms that render and rebuild a payload, which is where a reader
finds out that a step kind is a wire format and not a local detail.
"""


@dataclass(frozen=True)
class ComposedStep:
    """One step of a procedure, under the id this system minted for it.

    The id sits beside the step rather than inside it, and that is the
    whole reason this class exists rather than a field on each member of
    the union above. A caller composes the step; this system names it. A
    field inside would put the two in one place and make every surface
    that parses a step have an opinion about where its id comes from.

    Keeping it out also keeps the union closed at two. An id on both
    members would mean either a third and fourth class for the id-less
    shape a caller sends, or an optional id that is absent exactly where
    the record is written.

    ## What the id is for

    An execution's step cites one of these. Without it the only way to
    say which definition a step came from is its position in two lists,
    and that correspondence is built by one zip in one decider and
    asserted nowhere.

    Citing it rather than copying out of it means the whole step is
    reachable from the execution: the plan, the parameters it was
    composed with, and the devices it declares. Nothing edits a
    procedure, so the reference cannot come to describe something other
    than what was dispatched.
    """

    id: UUID
    step: ProcedureStep


def _validated_move(index: int, step: MoveStep) -> MoveStep:
    """Trim a move and refuse one this system will not store."""
    record = step.record.strip()
    if not record:
        msg = f"Step {index} is a move that names no record"
        raise InvalidProcedureStepsError(msg)
    if len(record) > PROCEDURE_RECORD_MAX_LENGTH:
        msg = (
            f"Step {index} names a record of {len(record)} characters "
            f"and the bound is {PROCEDURE_RECORD_MAX_LENGTH}"
        )
        raise InvalidProcedureStepsError(msg)
    if not math.isfinite(step.to):
        msg = (
            f"Step {index} moves {record} to {step.to}, which JSON cannot carry, "
            "so the row would not survive a round trip through the log"
        )
        raise InvalidProcedureStepsError(msg)
    return MoveStep(record=record, to=step.to)


def _validated_acquire(index: int, step: AcquireStep) -> AcquireStep:
    """Trim an acquisition and refuse one this system will not store."""
    if not step.scopes:
        msg = (
            f"Step {index} is an acquisition declaring no devices; nothing here can "
            "derive them from the plan, and a step believed to touch nothing is one "
            "that can run beside another over the same motor"
        )
        raise InvalidProcedureStepsError(msg)
    if len(step.scopes) > PROCEDURE_MAX_SCOPES_PER_STEP:
        msg = (
            f"Step {index} declares {len(step.scopes)} scopes "
            f"and the bound is {PROCEDURE_MAX_SCOPES_PER_STEP}"
        )
        raise InvalidProcedureStepsError(msg)
    trimmed: list[str] = []
    for scope in step.scopes:
        cleaned = scope.strip()
        if not cleaned:
            msg = f"Step {index} declares a scope that is empty after trimming"
            raise InvalidProcedureStepsError(msg)
        if len(cleaned) > PROCEDURE_SCOPE_MAX_LENGTH:
            msg = (
                f"Step {index} declares a scope of {len(cleaned)} characters "
                f"and the bound is {PROCEDURE_SCOPE_MAX_LENGTH}"
            )
            raise InvalidProcedureStepsError(msg)
        trimmed.append(cleaned)
    return AcquireStep(
        plan_id=step.plan_id,
        parameters=dict(step.parameters),
        scopes=tuple(trimmed),
    )


def validated_steps(raw: tuple[ProcedureStep, ...]) -> tuple[ProcedureStep, ...]:
    """Trim a step list and refuse one this system will not store.

    Called on the way in by the decider and on the way out by the
    evolver, which is the same both-directions check a value object
    gives. A function rather than a value object because the thing being
    validated is the list, and a type per step would have to be unwrapped
    everywhere a reader wants a step.

    Says nothing about whether the plans the acquisitions cite exist.
    That needs a store and this is pure; the handler loads them and the
    decider checks what it is handed.
    """
    if not raw:
        msg = "A procedure must hold at least one step, because a routine of nothing runs nothing"
        raise InvalidProcedureStepsError(msg)
    if len(raw) > PROCEDURE_MAX_STEPS:
        msg = (
            f"A procedure may hold at most {PROCEDURE_MAX_STEPS} steps and this one holds "
            f"{len(raw)}; a routine that long belongs to an engine rather than to a conductor"
        )
        raise InvalidProcedureStepsError(msg)
    validated: list[ProcedureStep] = []
    for index, step in enumerate(raw):
        match step:
            case MoveStep():
                validated.append(_validated_move(index, step))
            case AcquireStep():
                validated.append(_validated_acquire(index, step))
    return tuple(validated)


def validated_composition(raw: tuple[ComposedStep, ...]) -> tuple[ComposedStep, ...]:
    """Trim a composed step list and refuse one this system will not store.

    What the evolver calls, where the decider calls `validated_steps`.
    The difference is only that these steps have been named: the checks
    are the same ones, run against the step inside each pairing, and the
    ids ride through untouched.

    The ids are not checked for uniqueness, for the reason an execution's
    are not: they are minted one apiece from the same generator that
    mints every other id here, so a collision would mean that generator
    is broken and the check would be testing the chassis on every fold.
    """
    validated = validated_steps(tuple(composed.step for composed in raw))
    return tuple(
        ComposedStep(id=composed.id, step=step)
        for composed, step in zip(raw, validated, strict=True)
    )


def describes(step: ProcedureStep) -> str:
    """One line saying what a step does, for a reader rather than a driver.

    An execution copies these onto its genesis so its record stays readable
    after the thing driving it has gone. They are for display, and only
    for display: a reader parsing one back into its parts is reading a
    sentence that this function is free to rewrite.

    An acquisition names its plan by id rather than by name. The name
    would read better and would mean loading a second stream per
    acquisition to build a string nothing acts on. The id appearing here
    is not how anything finds it; `runs_plan` below is.
    """
    match step:
        case MoveStep():
            return f"move {step.record} to {step.to}"
        case AcquireStep():
            return f"acquire {step.plan_id} over {', '.join(step.scopes)}"


def runs_plan(step: ProcedureStep) -> UUID | None:
    """The plan an acquisition hands to an engine, or None for a move.

    What anything holding a step of an execution ends up asking, after
    following that step's reference back to the definition here. Counsel
    is the caller today: it compares this against the plan a proposal
    named, and a None means the step was composed to drive a motor
    rather than to ask an engine for anything.

    A function here rather than an attribute test at the call site, so
    the answer moves with the step union. A third kind of step that runs
    no plan gets an arm returning None and nothing downstream changes.
    """
    match step:
        case MoveStep():
            return None
        case AcquireStep():
            return step.plan_id


@dataclass(frozen=True)
class Procedure:
    """A routine composed here, as the fold leaves it.

    No status field. Nothing retires a procedure yet, so a status would
    have one reachable value, and a one-valued field says less than no
    field while inviting a reader to believe a lifecycle is being
    enforced. It arrives with the command that flips it, the way a plan's
    would.

    `steps` are composed steps, so each carries the id this system minted
    for it at definition. That is what an execution's step cites, and it
    is why a reader here writes `composed.step` to reach the move or the
    acquisition itself.
    """

    id: UUID
    name: ProcedureName
    beamline: ProcedureBeamline
    steps: tuple[ComposedStep, ...]

    def step(self, step_id: UUID) -> ComposedStep | None:
        """The step with this id, or None if the procedure holds no such step.

        A search rather than an index, which is the point of the id. One
        procedure is dispatched many times and nothing outside holds a
        position into this list.
        """
        return next((composed for composed in self.steps if composed.id == step_id), None)


__all__ = [
    "PROCEDURE_BEAMLINE_MAX_LENGTH",
    "PROCEDURE_MAX_SCOPES_PER_STEP",
    "PROCEDURE_MAX_STEPS",
    "PROCEDURE_NAME_MAX_LENGTH",
    "PROCEDURE_RECORD_MAX_LENGTH",
    "PROCEDURE_SCOPE_MAX_LENGTH",
    "AcquireStep",
    "ComposedStep",
    "InvalidProcedureBeamlineError",
    "InvalidProcedureNameError",
    "InvalidProcedureParametersError",
    "InvalidProcedureStepsError",
    "MoveStep",
    "Procedure",
    "ProcedureAlreadyExistsError",
    "ProcedureBeamline",
    "ProcedureName",
    "ProcedureNotFoundError",
    "ProcedureStep",
    "ProcedureStepNotFoundError",
    "describes",
    "runs_plan",
    "validated_composition",
    "validated_steps",
]
