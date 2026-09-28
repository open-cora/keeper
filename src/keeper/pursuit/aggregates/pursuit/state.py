"""Pursuit state, its value objects, and its domain errors.

A pursuit is a bounded, goal-oriented, autonomous loop. It observes an
execution, asks what should run next, dispatches the answer, and observes
that in turn, toward one goal within one beamline, one set of scopes and
one budget, until the objective is met or a stopping condition is reached.

## What a pursuit is for

Advice can become work: a proposal names an operation and its values, and
adopting one composes a procedure and dispatches an execution. What
adopting cannot do on its own is decide that it should happen. Two of the
three facts a procedure needs beyond the proposal are safety-bearing, the
beamline it runs at and the scopes it may drive, and neither may be
inferred from anything. So a caller states them, every time, and the caller
that states them has to be a person.

A pursuit is where a person states them once. It is a standing
authorization with a goal attached and a limit on how far it may run,
written to a log nobody can edit. Everything that acts inside one is
checked against it, and every refusal is on the record beside it.

## Why the thing acting on it is not here

Nothing in this system reacts to an event by issuing a command, and a
pursuit does not change that. Something outside notices that an execution
ended and calls in, the way the work intake's caller notices that an
execution was dispatched. That caller holds no authority at all: it cannot
widen a scope, spend past a budget or reopen a stopped pursuit, because
this aggregate refuses all three.

It also needs no claim, which is worth stating because its nearest
neighbour does. Two conductors walking one procedure would move one motor
twice, so a conductor claims. Two callers driving one pursuit both append
at the version they folded, one wins, and the loser is refused by the round
it finds already there. The record is the thing that serializes them.

## What is deliberately not here

**The reasoning.** A pursuit records what it was authorized to do and what
it did. Why a thinker concluded what it concluded is the thinker's, and is
not recorded there either.

**A schedule.** Nothing says when a pursuit should next act. That is the
caller's business and a field here would be an instruction this system has
no way to carry out.

**Any claim on the beamline.** A pursuit names one and does not reserve it.
Two pursuits at one beamline are two records that happen to agree, and what
stops them colliding is the same thing that stops two operators colliding.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from keeper.shared.bounded_text import bounded_name

PURSUIT_GOAL_MAX_LENGTH = 500
"""The longest goal this record will hold.

The same bound Counsel puts on an inquiry's objective, declared again here
rather than shared, because the two are declared on two aggregates and
nothing stops one moving. A pursuit's goal becomes the objective of every
inquiry it opens, so a goal this record accepts and that one refuses would
be a pursuit that cannot take its first step.
"""

PURSUIT_BEAMLINE_MAX_LENGTH = 100
"""The longest beamline name this record will hold.

Matched to Execution's bound for the same reason and with the same
independence: a procedure composed inside a pursuit carries the beamline
across, and a value only one of the two accepts would fail at the far end.
"""

PURSUIT_SCOPE_MAX_LENGTH = 200
"""How long one authorized scope may be."""

PURSUIT_MAX_SCOPES = 100
"""How many scopes one pursuit may be authorized over.

Matched to the bound Execution puts on one run's declared scopes,
because a pursuit's scopes are what every run it dispatches will
declare. A pursuit allowed more than a step could carry would authorize
something it can never spend.
"""


class InvalidPursuitGoalError(ValueError):
    """The goal was empty after trimming, or longer than the bound."""

    def __init__(self, value: str) -> None:
        super().__init__(
            f"Pursuit goal must be 1 to {PURSUIT_GOAL_MAX_LENGTH} characters "
            f"after trimming, got {len(value.strip())}"
        )
        self.value = value


class InvalidPursuitBeamlineError(ValueError):
    """The beamline was empty after trimming, or longer than the bound."""

    def __init__(self, value: str) -> None:
        super().__init__(
            f"Pursuit beamline must be 1 to {PURSUIT_BEAMLINE_MAX_LENGTH} characters "
            f"after trimming, got {len(value.strip())}"
        )
        self.value = value


@bounded_name(max_length=PURSUIT_GOAL_MAX_LENGTH, error_class=InvalidPursuitGoalError)
@dataclass(frozen=True)
class PursuitGoal:
    """What the loop is toward, in the words of whoever authorized it.

    Free text, bounded and trimmed, and load-bearing in a way an inquiry's
    objective on its own is not. Every inquiry a pursuit opens carries this
    same goal unchanged, which is what makes a thinker's `Stop` mean
    something: that conclusion is a claim that the objective is met, and its
    own account of itself says it is only as good as the objective it was
    given. A goal restated per round would leave nothing for `Stop` to be
    about.

    Ask a different question and it is a different pursuit.
    """

    value: str


@bounded_name(max_length=PURSUIT_BEAMLINE_MAX_LENGTH, error_class=InvalidPursuitBeamlineError)
@dataclass(frozen=True)
class PursuitBeamline:
    """Which beamline everything inside this pursuit runs at.

    Stated once by whoever authorized the pursuit, and never again. This is
    the first of the two safety-bearing facts a proposal underdetermines,
    and the whole reason adopting one has to be told them rather than
    working them out.

    Bounded here as well as on an execution, for the reason a procedure's
    name is bounded in both places: two aggregates declare it and nothing
    stops one moving.
    """

    value: str


class InvalidPursuitScopesError(ValueError):
    """A scope was empty, over its bound, or there were too many of them."""

    def __init__(self, reason: str) -> None:
        super().__init__(f"Pursuit scopes are invalid: {reason}")
        self.reason = reason


class BudgetDimension(StrEnum):
    """The resources a pursuit may be bounded in.

    Values are PascalCase strings so a log line or a response body reads
    without a mapping step, which is `ExecutionStatus`'s choice and for the
    same reason.

    The five split three ways, and the split decides what each one costs to
    support rather than being a tidy grouping.

    `ROUNDS` and `EXECUTIONS` are counted. A pursuit's own events hold both,
    so nothing reports them and nothing can misreport them. They are two
    numbers rather than one because a round that concluded without a
    proposal spent inference and no beamtime.

    `WALL_SECONDS` is derived. It is the clock against the moment the
    pursuit started, so it needs no event at all.

    `BEAM_SECONDS` and `TOKENS` are reported. Neither is knowable here: one
    is measured by whatever measures beam and the other is counted by a
    thinker, so both arrive from outside and are only as honest as whoever
    sent them. A pursuit is a governor, not an accounting system, and these
    two are the reason that sentence is in this docstring.
    """

    ROUNDS = "Rounds"
    EXECUTIONS = "Executions"
    WALL_SECONDS = "WallSeconds"
    BEAM_SECONDS = "BeamSeconds"
    TOKENS = "Tokens"

    @property
    def is_reported(self) -> bool:
        """Whether this dimension can only be learned from outside.

        The two that can are the two a charge may name. The other three
        are computed from the pursuit's own events and the clock, so a
        charge against one of them would be counted twice: once by the
        record and once by whoever sent it.

        Written as a positive list of the reported pair rather than as
        the complement of the computed three, because a dimension added
        later is far more likely to be reported than computed, and the
        complement would let it through by default.
        """
        return self in (BudgetDimension.BEAM_SECONDS, BudgetDimension.TOKENS)


class InvalidPursuitBudgetError(ValueError):
    """A budget named no dimension, or gave one a limit that is not positive."""

    def __init__(self, reason: str) -> None:
        super().__init__(f"Pursuit budget is invalid: {reason}")
        self.reason = reason


@dataclass(frozen=True)
class Budget:
    """Bounded consumption across one or more dimensions, whichever runs out first.

    A mapping rather than a row of nullable columns, because the dimensions
    a facility cares about are not the same everywhere and a pursuit
    bounded only in tokens is as legitimate as one bounded only in hours.
    At least one is required: a loop with no limit at all is the thing this
    aggregate exists to make impossible.

    Enforced in exactly one place, and a reader should not infer more than
    that. Opening a round refuses when any bounded dimension has run out,
    so what a budget limits is how many more times the loop may turn.
    Nothing stops a round already open from closing, and nothing refuses a
    charge that carries a dimension past its limit, because both of those
    describe consumption that already happened.
    """

    limits: Mapping[BudgetDimension, int]

    def __post_init__(self) -> None:
        """Refuse a budget that bounds nothing.

        On the value object rather than in the decider, so the same check
        runs on the way in and on the way back out of the log. A limit that
        has gone non-positive in storage fails at the fold rather than
        reaching a reader as a bound nothing can satisfy.
        """
        if not self.limits:
            raise InvalidPursuitBudgetError("it names no dimension")
        for dimension, limit in self.limits.items():
            if limit <= 0:
                raise InvalidPursuitBudgetError(f"{dimension} has a limit of {limit}")


class RoundOutcome(StrEnum):
    """How a round ended, as this record holds it.

    Four values rather than four event classes, which is a departure from
    how an execution's step outcomes are modelled and is the same
    departure `InquiryConclusion` makes, for the same reason. Those four
    arrive from different reporting paths and carry different fields, so
    four classes make four wrong states unrepresentable. These four arrive
    from one call and three of them carry nothing beyond the round they
    closed, so the difference between them is one bit rather than four
    shapes.

    They are this context's words rather than the thinker's, although each
    answers to one of its conclusions. A round that ends because a thinker
    proposed something has advanced, which is a fact about the loop; that
    the thinker said Propose is a fact about the inquiry, and the round
    cites the inquiry rather than copying what it holds.

    Only `ADVANCED` leaves the pursuit running. That asymmetry is the
    whole control flow: a loop continues while there is something to run
    and stops or waits otherwise.
    """

    ADVANCED = "Advanced"
    COMPLETED = "Completed"
    STALLED = "Stalled"
    REFERRED = "Referred"

    @property
    def holds(self) -> bool:
        """Whether this outcome pauses the pursuit rather than ending it.

        Two of the four, and what they have in common is that a person
        could reasonably want the loop to carry on afterwards. Nothing to
        go on may stop being true when more data lands, and a referral is
        answered by whoever was referred to. Neither is a reason to throw
        the authorization away, so both are reversible and `COMPLETED` is
        not.
        """
        return self in (RoundOutcome.STALLED, RoundOutcome.REFERRED)


class PursuitRoundCannotBeOpenedError(Exception):
    """A round was asked for on a pursuit that cannot open one.

    Per verb rather than collapsed onto a shared transition error, which is
    R6 in docs/reference/naming.md. Named for the round rather than for the
    pursuit because the round is what was refused, the way
    `ExecutionStepNotFoundError` is named for the step.

    `reason` says which of the three refusals it was, because they call for
    opposite responses. A stopped pursuit is finished. An exhausted one
    needs a person to decide whether to authorize more. One already asking
    about that execution has the answer coming, and the caller should wait
    rather than do anything.
    """

    def __init__(self, pursuit_id: UUID, reason: str) -> None:
        super().__init__(f"Pursuit {pursuit_id} cannot open a round: {reason}")
        self.pursuit_id = pursuit_id
        self.reason = reason


class InvalidPursuitChargeError(ValueError):
    """A charge named an amount, or a dimension, this record will not take.

    A `ValueError` rather than a conflict, because none of the three causes
    is about the state the pursuit is in. An amount that is not positive, a
    dimension this system computes for itself, and a dimension the pursuit
    was never bounded in are all malformed rather than untimely.
    """

    def __init__(self, pursuit_id: UUID, reason: str) -> None:
        super().__init__(f"Pursuit {pursuit_id} cannot be charged: {reason}")
        self.pursuit_id = pursuit_id
        self.reason = reason


class PursuitRoundCannotBeClosedError(Exception):
    """A round was closed that cannot be, or by something that cannot close it.

    Per verb rather than collapsed onto a shared transition error, which is
    R6 in docs/reference/naming.md, and named for the round beside the
    error that refuses opening one.

    `reason` says which refusal it was, because they mean different things
    to whoever is driving. A round that does not exist is a caller with the
    wrong number. One already closed is a retry, and the answer is already
    on the record. An inquiry with no answer yet is nobody's fault and the
    caller should wait.
    """

    def __init__(self, pursuit_id: UUID, round_index: int, reason: str) -> None:
        super().__init__(f"Round {round_index} of pursuit {pursuit_id} cannot be closed: {reason}")
        self.pursuit_id = pursuit_id
        self.round_index = round_index
        self.reason = reason


@dataclass(frozen=True, slots=True)
class PursuitRound:
    """One turn of the loop: what was observed, and what was asked about it.

    Numbered from zero, in the order the pursuit opened them, the way an
    execution's steps are. The index is what a caller names to close one,
    because a round has no id of its own: it is an element of a list one
    pursuit accumulates rather than a record anything else points at.

    `execution_id` is what this round observed. It is also the retry guard:
    a caller that crashed and came back cannot open a second round about
    the same execution, which is what lets the thing driving a pursuit be
    duplicated without coordinating.

    `outcome` is None while the round is open and set once it closes. It
    is this context's word for what the thinker concluded rather than a
    copy of the conclusion, which stays on the inquiry one hop away.

    `proposal_id` and `dispatched_id` are set together and only on an
    advance, because they are the two halves of one fact: the advice that
    was taken up, and the work it became. Neither can be present without
    the other, and the decider is what keeps that true.
    """

    index: int
    execution_id: UUID
    inquiry_id: UUID
    outcome: RoundOutcome | None = None
    proposal_id: UUID | None = None
    dispatched_id: UUID | None = None

    @property
    def is_open(self) -> bool:
        """Whether this round is still waiting on an answer."""
        return self.outcome is None


class PursuitStatus(StrEnum):
    """How far a pursuit has got.

    Values are PascalCase strings so a log line or a response body reads
    without a mapping step, which is `ExecutionStatus`'s choice and for the
    same reason.

    Derived in the fold from which events the stream carries, never stored.
    A status written onto a payload could contradict the event it rode in
    on, and the fold would have to pick a winner.
    """

    RUNNING = "Running"
    HELD = "Held"
    STOPPED = "Stopped"

    @property
    def is_terminal(self) -> bool:
        """Whether no further event can land on a pursuit in this status.

        Written as a positive list of the terminals rather than as the
        complement of the live ones, because "terminal" is what the property
        is called and a reader should not have to invert it.
        """
        return self is PursuitStatus.STOPPED


class PursuitNotFoundError(Exception):
    """A command or query named a pursuit id with no stream behind it."""

    def __init__(self, pursuit_id: UUID) -> None:
        super().__init__(f"Pursuit {pursuit_id} not found")
        self.pursuit_id = pursuit_id


class PursuitAlreadyExistsError(Exception):
    """Starting one was attempted against an id that already has a stream.

    Unreachable through the ordinary path, because the handler mints a fresh
    id and a fresh id has no history. It exists so the decider states the
    precondition it relies on rather than assuming it.
    """

    def __init__(self, pursuit_id: UUID) -> None:
        super().__init__(f"Pursuit {pursuit_id} already exists")
        self.pursuit_id = pursuit_id


class PursuitCannotBeResumedError(Exception):
    """A resume arrived on a pursuit that was not being held.

    A running pursuit needs no resuming and a stopped one cannot be, so
    both are refused rather than treated as a no-op. The second is the one
    worth refusing loudly: resuming a completed pursuit would be restarting
    a loop somebody decided was finished, and doing that quietly is how an
    authorization outlives the intention behind it.
    """

    def __init__(self, pursuit_id: UUID, status: PursuitStatus) -> None:
        super().__init__(f"Pursuit {pursuit_id} cannot be resumed while {status}")
        self.pursuit_id = pursuit_id
        self.status = status


class PursuitCannotBeWithdrawnError(Exception):
    """A withdrawal arrived on a pursuit that had already stopped.

    Per verb rather than collapsed onto a shared transition error, which is
    R6 in docs/reference/naming.md.

    Refused rather than treated as a repeat that changed nothing, because
    the two are different facts and a reader of the log should be able to
    tell a pursuit somebody stopped from one that stopped itself. A second
    withdrawal would overwrite the first account of why it ended.
    """

    def __init__(self, pursuit_id: UUID, status: PursuitStatus) -> None:
        super().__init__(f"Pursuit {pursuit_id} cannot be withdrawn while {status}")
        self.pursuit_id = pursuit_id
        self.status = status


@dataclass(frozen=True)
class Pursuit:
    """A standing authorization to pursue a goal, as the fold leaves it.

    `actor_id` is whoever authorized it, written by the handler from the
    authenticated principal rather than supplied by the caller, the way a
    proposal's proposer and an inquiry's asker are. Who authorized a loop
    is the most load-bearing fact on this record, and the envelope that
    carries the principal is infrastructure the fold never sees.

    `beamline` and `scopes` are the two safety-bearing facts. They are held
    here rather than passed per act precisely so that acting inside a
    pursuit is a statement already made being applied, rather than a
    machine inferring one.

    `started_at` is the envelope's moment for the genesis, carried onto the
    state because one budget dimension is measured against it. It is the
    only timestamp this aggregate keeps.

    `rounds` does three jobs, which is why one tuple carries them all. It
    is the retry guard, the counter behind two budget dimensions, and the
    audit trail of what this one authorization actually caused.

    `charged` holds only the two dimensions nothing here can measure. The
    other three are computed in `spent`, so a number appearing here for one
    of them would be counted twice, and the charge that would have written
    it is refused.

    `stopped_by` is whoever withdrew it, and is None on a running pursuit
    and on any other way of stopping. There is one other way at present and
    it is not modelled here yet.
    """

    id: UUID
    actor_id: UUID
    goal: PursuitGoal
    beamline: PursuitBeamline
    scopes: tuple[str, ...]
    budget: Budget
    started_at: datetime
    status: PursuitStatus
    rounds: tuple[PursuitRound, ...] = ()
    charged: Mapping[BudgetDimension, int] = field(default_factory=dict[BudgetDimension, int])
    stopped_by: UUID | None = None

    @property
    def is_running(self) -> bool:
        """Whether anything may still act inside this pursuit.

        A property rather than a stored flag, for the reason the status is
        derived: a field a writer can set is a field a writer can set wrong,
        and this one cannot disagree with the status it reads.
        """
        return self.status is PursuitStatus.RUNNING

    @property
    def held_for(self) -> RoundOutcome | None:
        """Why the pursuit is waiting, or None if it is not.

        Derived from the round that put it there rather than stored, for
        the reason the status is: a field a writer can set is a field a
        writer can set wrong, and this one cannot disagree with the round
        it reads.

        The two it can be are the two a person triaging a list of held
        pursuits needs to tell apart. One is waiting for them. The other
        ran out of ideas and may be worth more data rather than more
        attention.
        """
        if self.status is not PursuitStatus.HELD or not self.rounds:
            return None
        return self.rounds[-1].outcome

    def round_at(self, index: int) -> PursuitRound | None:
        """The round with this number, or None if the pursuit has no such round.

        By search rather than by position, because the number is a fact the
        event carries rather than a place in a list, and the two would only
        agree for as long as nothing is ever removed.
        """
        return next((turn for turn in self.rounds if turn.index == index), None)

    def spent(self, *, now: datetime) -> dict[BudgetDimension, int]:
        """Consumption so far, in every dimension, however it is learned.

        The three groups the dimensions split into arrive here by three
        different routes and the method is the only place they meet.
        Rounds and executions are counted off this pursuit's own history,
        wall seconds come from the clock the caller passed, and the two
        reported ones are read out of what somebody charged.

        A dimension the budget does not bound still gets a number. It costs
        nothing, and a caller reading this to show somebody where a pursuit
        has got to wants all five rather than only the bounded ones.
        """
        return {
            BudgetDimension.ROUNDS: len(self.rounds),
            BudgetDimension.EXECUTIONS: sum(
                1 for turn in self.rounds if turn.dispatched_id is not None
            ),
            BudgetDimension.WALL_SECONDS: max(0, int((now - self.started_at).total_seconds())),
            BudgetDimension.BEAM_SECONDS: self.charged.get(BudgetDimension.BEAM_SECONDS, 0),
            BudgetDimension.TOKENS: self.charged.get(BudgetDimension.TOKENS, 0),
        }

    def exhausted_by(self, *, now: datetime) -> BudgetDimension | None:
        """The first bounded dimension that has run out, or None.

        Whichever comes first, which is what a budget across several
        dimensions means. The enum's declaration order decides which is
        reported when two run out together, so the answer is the same on
        every machine and does not depend on how a mapping happened to
        iterate.

        Derived rather than recorded, which is the same choice the status
        makes and for a stronger reason. One dimension is the clock, so a
        pursuit runs out of wall time at a moment nobody is present for. An
        event would have to be written by whoever next called in, which
        would date the exhaustion to the discovery rather than to when it
        happened, and a pursuit nobody called about again would never get
        one at all.

        So there is no exhaustion event, and no status for it. What a
        reader sees is a pursuit still authorized and a dimension with
        nothing left, which are two true facts rather than one invented
        one.
        """
        spent = self.spent(now=now)
        return next(
            (
                dimension
                for dimension in BudgetDimension
                if dimension in self.budget.limits
                and spent[dimension] >= self.budget.limits[dimension]
            ),
            None,
        )

    def has_observed(self, execution_id: UUID) -> bool:
        """Whether a round of this pursuit already asked about that execution.

        The retry guard, and the reason nothing has to claim a pursuit. A
        driver that crashed between opening a round and hearing about it
        comes back, tries the same execution, and is refused rather than
        opening a second round and spending the budget twice.
        """
        return any(turn.execution_id == execution_id for turn in self.rounds)


def validate_scopes(scopes: tuple[str, ...]) -> tuple[str, ...]:
    """Return the scopes trimmed, or raise if they cannot be authorized.

    A function rather than a value object, because the thing being bounded
    is the tuple and not any one member, and a wrapper type around a tuple
    of strings would be a name for the parentheses. Execution checks the
    same shape the same way on a run's declared scopes.

    An empty tuple is refused. A pursuit authorized over nothing could
    dispatch nothing, and recording one would be recording an intention
    that cannot be acted on.
    """
    if not scopes:
        raise InvalidPursuitScopesError("a pursuit must be authorized over at least one scope")
    if len(scopes) > PURSUIT_MAX_SCOPES:
        raise InvalidPursuitScopesError(
            f"there are {len(scopes)} and the bound is {PURSUIT_MAX_SCOPES}"
        )
    cleaned: list[str] = []
    for scope in scopes:
        trimmed = scope.strip()
        if not trimmed:
            raise InvalidPursuitScopesError("one of them is empty")
        if len(trimmed) > PURSUIT_SCOPE_MAX_LENGTH:
            raise InvalidPursuitScopesError(
                f"{trimmed[:20]!r} is {len(trimmed)} characters "
                f"and the bound is {PURSUIT_SCOPE_MAX_LENGTH}"
            )
        cleaned.append(trimmed)
    return tuple(cleaned)


__all__ = [
    "PURSUIT_BEAMLINE_MAX_LENGTH",
    "PURSUIT_GOAL_MAX_LENGTH",
    "PURSUIT_MAX_SCOPES",
    "PURSUIT_SCOPE_MAX_LENGTH",
    "Budget",
    "BudgetDimension",
    "InvalidPursuitBeamlineError",
    "InvalidPursuitBudgetError",
    "InvalidPursuitChargeError",
    "InvalidPursuitGoalError",
    "InvalidPursuitScopesError",
    "Pursuit",
    "PursuitAlreadyExistsError",
    "PursuitBeamline",
    "PursuitCannotBeResumedError",
    "PursuitCannotBeWithdrawnError",
    "PursuitGoal",
    "PursuitNotFoundError",
    "PursuitRound",
    "PursuitRoundCannotBeClosedError",
    "PursuitRoundCannotBeOpenedError",
    "PursuitStatus",
    "RoundOutcome",
    "validate_scopes",
]
