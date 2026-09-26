"""Inquiry state, its value objects, and its domain errors.

An Inquiry is one question put to a thinker about one execution, and what
came back.

## What an inquiry is

A thinker reads an execution back, pairs what the procedure asked for with
what became of it, and concludes one of four things. Before this aggregate
existed the asking was an argument on a command line and three of those four
conclusions had nowhere to land, so the only thinking this system could see
was the arm that happened to write a proposal.

An inquiry is the record of the asking. It says who asked, about which
execution, what they wanted to know, and what the thinker concluded. It does
not say how the thinker reached it.

## Why it is here and not in Execution

An execution is one traversal of a procedure and its stream is what became
of that traversal. A question somebody asked about it afterwards is not
something that became of it, and an inquiry that concluded nothing worth
running would sit in every count of how far the execution got. That is the
same argument that keeps a proposal off an execution's step list.

It sits beside Proposal because both are advice: one is advice put forward,
the other is advice asked for. The `Propose` arm writes a proposal, so the
two aggregates are one door apart rather than one context apart.

## What is deliberately not here

**The case.** The thinker pairs the procedure with the record and hands the
whole pairing to whatever does the thinking. None of it is copied here.
`execution_id` reaches all of it, which makes this the one record in the
tree that can point at its own basis rather than restating it.

**The reasoning, and any confidence.** What the thinker said and how sure it
was are both assertions this system did not witness. Recording them would
claim the cognition, which is the objection that kept the Proposal
aggregate from being called a Decision.

**Which thinker, beyond the principal.** An actor is whoever authenticated,
and Access holds no marker saying whether that was a person or a piece of
software. A field here would be a copy of a fact another context does not
have.

## The observation boundary, and why the record carries it

An inquiry may name an execution that is still walking. A conclusion drawn
from two reported steps of six is a weaker claim than the same conclusion
drawn from six of six, and nothing downstream can tell them apart after the
fact: by the time anybody reads the inquiry the execution has moved on.

So the boundary is written down. `execution_step_count` is captured when the
question is put, from the execution itself, and cannot drift afterwards
because an execution's steps ride its genesis. `observed_step_count` and
`execution_ended` arrive with the answer and are the thinker's own account
of what it had in front of it.

Those are two different questions and both are worth keeping. An execution
can be closed with steps nobody reported on, and one that has an outcome for
every step has not necessarily been closed. A single number would collapse
them.

None of the three is a quality score. They say how much was visible, never
whether the conclusion was good.
"""

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from keeper.shared.bounded_text import bounded_name

INQUIRY_OBJECTIVE_MAX_LENGTH = 500
"""The longest objective this record will hold.

Long enough for the question somebody actually typed, short enough that a
page of summaries is not mostly prose. Counsel holds no other free text, and
this one earns its place because a conclusion cannot be read without the
question it answers.
"""


class InvalidInquiryObjectiveError(ValueError):
    """The objective was empty after trimming, or longer than the bound."""

    def __init__(self, value: str) -> None:
        super().__init__(
            f"Inquiry objective must be 1 to {INQUIRY_OBJECTIVE_MAX_LENGTH} characters "
            f"after trimming, got {len(value.strip())}"
        )
        self.value = value


@bounded_name(
    max_length=INQUIRY_OBJECTIVE_MAX_LENGTH,
    error_class=InvalidInquiryObjectiveError,
)
@dataclass(frozen=True)
class InquiryObjective:
    """What the asker wanted to know, in their own words.

    The one piece of free text in this context, and the argument for it is
    that the alternative is worse. A proposer's rationale was refused here
    because it is unbounded self-justification that will eventually quote a
    person. An objective is the input rather than the defence: the thinker
    is asked what should run next in pursuit of something, and a record of
    the answer without the something is a record nobody can check.

    Bounded and trimmed, so it cannot grow into the reasoning the record
    declines to hold.
    """

    value: str


class InquiryStatus(StrEnum):
    """How far an inquiry has got.

    Values are PascalCase strings so a log line or a response body reads
    without a mapping step, which is `ExecutionStatus`'s choice and for the
    same reason.

    Derived in the fold from which events the stream carries, never stored.
    A status written onto a payload could contradict the event it rode in
    on, and the fold would have to pick a winner.

    Two live and one terminal. There is no running state between them: an
    execution reaches one when a step is reported, and a thinking has no
    steps to report. It is read, conclude, advise, and the record hears
    about it once.
    """

    OPEN = "Open"
    CLAIMED = "Claimed"
    ANSWERED = "Answered"

    @property
    def is_terminal(self) -> bool:
        """Whether no further event can land on an inquiry in this status.

        Written as a positive list of the terminals rather than as the
        complement of the live ones, because "terminal" is what the property
        is called and a reader should not have to invert it.
        """
        return self is InquiryStatus.ANSWERED


class InquiryConclusion(StrEnum):
    """The four things a thinker may conclude, as this record holds them.

    Four values rather than four event classes, which is a departure from
    how an execution's step outcomes are modelled and the reason is the
    payloads. Those four arrive from different reporting paths and carry
    different fields, so four classes make four wrong states unrepresentable.
    These four arrive from one call and three of them carry nothing at all,
    so the difference between them is one bit rather than four shapes.

    What that trades away is a field that can be set wrong, and the decider
    is where it is caught: only `PROPOSE` may carry a proposal.

    The four words are the thinker's own, spelled the same on both sides of
    the wire so that nothing has to translate them. There is no shared
    package holding them, which is the same arrangement the conductor has
    with this system and is pinned by a test on each side rather than by an
    import.
    """

    PROPOSE = "Propose"
    STOP = "Stop"
    ABSTAIN = "Abstain"
    REFER = "Refer"


class InquiryNotFoundError(Exception):
    """A command or query named an inquiry id with no stream behind it."""

    def __init__(self, inquiry_id: UUID) -> None:
        super().__init__(f"Inquiry {inquiry_id} not found")
        self.inquiry_id = inquiry_id


class InquiryAlreadyExistsError(Exception):
    """Making one was attempted against an id that already has a stream.

    Unreachable through the ordinary path, because the handler mints a fresh
    id and a fresh id has no history. It exists so the decider states the
    precondition it relies on rather than assuming it.
    """

    def __init__(self, inquiry_id: UUID) -> None:
        super().__init__(f"Inquiry {inquiry_id} already exists")
        self.inquiry_id = inquiry_id


class InquiryCannotBeClaimedError(Exception):
    """A claim arrived on an inquiry that was not open.

    Per verb rather than collapsed onto a shared transition error, which is
    R6 in docs/reference/naming.md. The two verbs on this stream refuse from
    overlapping statuses and a caller needs to know which one it tripped.
    """

    def __init__(self, inquiry_id: UUID, status: InquiryStatus) -> None:
        super().__init__(f"Inquiry {inquiry_id} cannot be claimed while {status}")
        self.inquiry_id = inquiry_id
        self.status = status


class InquiryCannotBeAnsweredError(Exception):
    """An answer arrived on an inquiry that already had one.

    A second thinking about one execution is a second question, not a
    revision of the first. Answering twice is refused for the reason taking
    a proposal twice is: the record would stop saying which answer the
    asker got.
    """

    def __init__(self, inquiry_id: UUID, status: InquiryStatus) -> None:
        super().__init__(f"Inquiry {inquiry_id} cannot be answered while {status}")
        self.inquiry_id = inquiry_id
        self.status = status


class InvalidInquiryObservationError(ValueError):
    """The observation boundary the answer reported cannot be true.

    A thinker cannot have seen more steps than the execution had when the
    question was put, because an execution's steps ride its genesis and
    their number never changes afterwards.
    """

    def __init__(self, inquiry_id: UUID, observed: int, of: int) -> None:
        super().__init__(
            f"Inquiry {inquiry_id} was answered from {observed} observed step(s), "
            f"but the execution has {of}"
        )
        self.inquiry_id = inquiry_id
        self.observed = observed
        self.of = of


class InvalidInquiryConclusionError(ValueError):
    """A conclusion and the proposal beside it disagree.

    Two causes, and they are opposite mistakes, so the class carries a
    `cause` naming which one arrived. Without it a caller reading only the
    class learns that something about the pair was wrong and not which half
    to fix, which is a lesson this context has already paid for once.
    """

    def __init__(self, inquiry_id: UUID, conclusion: InquiryConclusion, *, cause: str) -> None:
        super().__init__(f"Inquiry {inquiry_id} concluded {conclusion} but {cause}")
        self.inquiry_id = inquiry_id
        self.conclusion = conclusion
        self.cause = cause


@dataclass(frozen=True)
class Inquiry:
    """A question put to a thinker, as the fold leaves it.

    `actor_id` is whoever asked, written by the handler from the
    authenticated principal rather than supplied by the caller, the way a
    proposal's proposer is. Who asked a question is a domain fact and the
    envelope that carries the principal is infrastructure the fold never
    sees.

    `execution_id` is what the question is about, and it is the whole of the
    basis. It is cited and never copied, which is the posture every record
    in this tree that names another stream takes.

    `execution_step_count` is how many steps that execution had when the
    question was put. Captured rather than cited, because it is the
    denominator of the observation boundary and a reader should not have to
    fetch a second stream to find out whether "three observed" meant all of
    them. It cannot go stale: an execution's steps are written by its
    genesis and no later event adds one.

    `conclusion`, `observed_step_count` and `execution_ended` are None until
    the inquiry is answered, and after that none of them is. All four fields
    below the status are written by one arm of the fold from one event that
    carries them all, so a half-answered inquiry is not a state this can
    reach and nothing here defends against one.

    `proposal_id` is set on the `PROPOSE` arm and on no other. That is the
    one thing the answer event could carry wrongly, and the decider refuses
    it in both directions.
    """

    id: UUID
    actor_id: UUID
    execution_id: UUID
    objective: InquiryObjective
    execution_step_count: int
    status: InquiryStatus
    conclusion: InquiryConclusion | None = None
    observed_step_count: int | None = None
    execution_ended: bool | None = None
    proposal_id: UUID | None = None

    @property
    def is_answered(self) -> bool:
        """Whether a thinker has concluded anything about this question.

        A property rather than a stored flag, for the reason the status is
        derived: a field a writer can set is a field a writer can set wrong,
        and this one cannot disagree with the status it reads.
        """
        return self.status is InquiryStatus.ANSWERED

    @property
    def covers_every_step(self) -> bool:
        """Whether the thinker saw an outcome for every step the execution has.

        False while the inquiry is unanswered, because nothing has been seen
        yet. It says how much was visible and never whether the conclusion
        drawn from it was right.
        """
        return self.observed_step_count == self.execution_step_count


__all__ = [
    "INQUIRY_OBJECTIVE_MAX_LENGTH",
    "Inquiry",
    "InquiryAlreadyExistsError",
    "InquiryCannotBeAnsweredError",
    "InquiryCannotBeClaimedError",
    "InquiryConclusion",
    "InquiryNotFoundError",
    "InquiryObjective",
    "InquiryStatus",
    "InvalidInquiryConclusionError",
    "InvalidInquiryObjectiveError",
    "InvalidInquiryObservationError",
]
