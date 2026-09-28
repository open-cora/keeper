"""Proposal state and its domain errors.

A Proposal is a run an actor put forward, before anything has run it.

## Who an actor is here

Whoever authenticated. The principal must be an active Actor in Access,
and an actor there is a person, a service account or a background
process, so a scientist putting a run forward and a piece of software
doing it produce the same record. Nothing in this context asks which,
and which of them a deployment permits is Authority's to say rather
than this aggregate's.

That is also why nothing here records the kind. It would be a copy of a
fact Access owns, and Access does not hold one today, so "was this run
human-directed" is a question the record cannot answer. If it needs
answering, a typed marker on the Actor is where it goes.

## What it is not

It cites an operation, it does not contain one, which is the posture every
record in this tree that names an operation takes for the same reason: the
operation is a record on another stream, and a copy here would go stale the
first time somebody defined a new one.

That leaves a proposal carrying what a run step carries, and
the difference between them is that one happened. A run is a
step of a procedure this system composed and dispatched, so something
drove it. A proposal points at nothing at all. That is not a missing
field, it is the whole distinction: this is the one record in the tree
that refers to no act.

## Why this is not a status on an Execution

Modelling a proposal as a step nothing has driven yet would save a
context, and two things stop it.

A step does not exist on its own. It is an entity inside an execution,
which exists because a procedure was dispatched, so a proposal modelled
as a step would need a procedure composed and handed out before anybody
had agreed the work should happen. That is the wrong order: proposing is
what comes before composing.

And a proposal nothing came of would be a step nobody drove, sitting in
every count of how far its execution got.

## Why there is a status field now, when there was not

`execution_id is None` used to be the whole of it, and this page said an
enum would arrive at the third state. Adoption is that third state.

Two ways a proposal can stop being open, and the null test cannot tell
them apart: this system chose it and committed work, or something
outside ran what it proposed and said so afterwards. Both set the same
two fields. The status is what carries the difference, and it is derived
in the fold from which event landed rather than stored, because a status
written onto a payload could contradict the event it rode in on.

Withdrawing and superseding are still the two foreseeable members after
these three.

Open is the honest default and stays honest the way Dispatched does: it
says only that nothing has been recorded against this proposal. A
proposal nobody acted on reads as open forever, and closing that needs
something watching rather than another value.
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import Any
from uuid import UUID


class ProposalStatus(StrEnum):
    """What became of the advice, as one word.

    Values are PascalCase strings so a log line or a response body reads
    without a mapping step, which is `ExecutionStatus`'s choice and
    `InquiryStatus`'s beside it.

    Derived in the fold from which event landed, never stored.

    Two of the three close the proposal and they are not the same fact.
    `ADOPTED` says this system chose the proposal, chose a beamline and a
    bound for it, and committed the facility: a decision made here, at
    the moment it is written. `TAKEN` says nobody here decided, and a
    step exists somewhere that ran what was proposed.

    There is no terminal property. Unlike an execution or an inquiry,
    nothing further is expected on this stream after either of the two,
    so a reader asking whether more can land is asking a question with
    one answer.
    """

    OPEN = "Open"
    ADOPTED = "Adopted"
    TAKEN = "Taken"


class ProposalCannotBeAdoptedError(Exception):
    """Adoption was attempted on a proposal that was not open.

    Per verb rather than collapsed onto a shared transition error, which
    is R6 in docs/reference/naming.md, and the status is on it because
    the two refusals mean different things. Already adopted is the
    facility committed twice to one piece of advice; already taken is
    advice something else acted on, where composing more work would run
    it a second time.
    """

    def __init__(self, proposal_id: UUID, status: "ProposalStatus") -> None:
        super().__init__(f"Proposal {proposal_id} cannot be adopted while {status}")
        self.proposal_id = proposal_id
        self.status = status


class ProposalNotFoundError(Exception):
    """A query named a proposal id with no stream behind it."""

    def __init__(self, proposal_id: UUID) -> None:
        super().__init__(f"Proposal {proposal_id} not found")
        self.proposal_id = proposal_id


class ProposalAlreadyExistsError(Exception):
    """Making one was attempted against an id that already has a stream.

    Unreachable through the ordinary path, because the handler mints a
    fresh id and a fresh id has no history. It exists so the decider
    states the precondition it relies on rather than assuming it.
    """

    def __init__(self, proposal_id: UUID) -> None:
        super().__init__(f"Proposal {proposal_id} already exists")
        self.proposal_id = proposal_id


class InvalidProposalParametersError(ValueError):
    """The proposed values do not satisfy the operation's declared schema.

    A proposal that could not be run is not a proposal, so the values
    are checked against the same schema, by the same shared validator,
    that checks a run's. Its own class rather than Execution's,
    because the two are refused on different surfaces and a caller
    reading `InvalidProcedureParametersError` from a proposal endpoint
    would go looking for a procedure.
    """


class ProposalCannotBeTakenError(Exception):
    """A run cannot be recorded against this proposal.

    Three causes, one class, which is the shape
    `ExecutionCannotBeClaimedError` also takes: one verb, more than one
    way to be refused, and the discriminating state carried on the error
    rather than split across class names. R6 is about not collapsing
    several VERBS into one class, and there is one verb here.

    The causes are told apart by which attribute is set. `taken_by` set
    means the proposal already has a step against it. `step_operation_id` set
    means the cited step ran a different operation from the one proposed, and
    the two operation ids say which. Neither set means the cited step runs no
    operation at all, which is a set.

    The third cause arrived with the step reference and is genuinely
    distinct rather than a mismatch against nothing. A mismatch tells a
    caller it resolved the wrong run; this tells it that what it
    resolved is not a run, so the fix is not to go looking for
    a closer match.

    All three are 409 because the caller's next move is the same in
    kind: stop, and work out which step it meant.
    """

    def __init__(
        self,
        proposal_id: UUID,
        detail: str,
        *,
        taken_by: UUID | None = None,
        proposed_operation_id: UUID | None = None,
        step_operation_id: UUID | None = None,
    ) -> None:
        super().__init__(f"Proposal {proposal_id} cannot be taken: {detail}")
        self.proposal_id = proposal_id
        self.taken_by = taken_by
        self.proposed_operation_id = proposed_operation_id
        self.step_operation_id = step_operation_id

    @classmethod
    def already_taken(cls, proposal_id: UUID, taken_by: UUID) -> "ProposalCannotBeTakenError":
        """A step is already recorded against it.

        `taken_by` is the step, not the execution around it. The step is
        what took the proposal, and an execution long enough to hold a
        thousand of them says almost nothing about which.
        """
        return cls(
            proposal_id,
            f"step {taken_by} already took it",
            taken_by=taken_by,
        )

    @classmethod
    def plan_mismatch(
        cls, proposal_id: UUID, *, proposed_operation_id: UUID, step_operation_id: UUID
    ) -> "ProposalCannotBeTakenError":
        """The cited run ran a different operation from the one proposed."""
        return cls(
            proposal_id,
            f"it proposes operation {proposed_operation_id} "
            f"and the step ran operation {step_operation_id}",
            proposed_operation_id=proposed_operation_id,
            step_operation_id=step_operation_id,
        )

    @classmethod
    def not_an_acquisition(cls, proposal_id: UUID, step_id: UUID) -> "ProposalCannotBeTakenError":
        """The cited step runs no operation, so it cannot have run this one.

        A set, today. What makes this refusable rather than merely
        false is that a proposal proposes running an operation, and a step
        that hands nothing to an engine has not run one whatever else it
        did.
        """
        return cls(
            proposal_id,
            f"step {step_id} runs no operation, and a proposal proposes running one",
        )


@dataclass(frozen=True)
class Proposal:
    """A run an actor put forward, as the fold leaves it.

    `actor_id` is whoever proposed, written by the handler from the
    authenticated principal rather than supplied by the caller. It
    duplicates the envelope's `principal_id` on purpose: the envelope is
    infrastructure and the fold never sees it, and who advised is a
    domain question that should be answerable from the domain record.

    Named for the aggregate it points at, the way `operation_id` is. The role
    it plays is carried by the record it sits on rather than by a second
    word in the field name.

    `execution_id` and `step_id` are None until a run is
    recorded against this proposal, and are what say whether it is still
    open. Two fields rather than one, because a step is an entity inside
    the Execution aggregate rather than a stream of its own, so the root
    is what makes the step findable and checkable. `Dataset` carries the
    same pair for the same reason, and the root comes first there too.

    Both nullable and never one without the other. They are written by
    one arm of the fold, from one event that carries both, so a state
    where only one is set is not reachable and nothing here defends
    against it.
    """

    id: UUID
    actor_id: UUID
    operation_id: UUID
    parameters: dict[str, Any]
    status: ProposalStatus = ProposalStatus.OPEN
    execution_id: UUID | None = None
    step_id: UUID | None = None

    @property
    def is_taken(self) -> bool:
        """Whether anything has come of this proposal, either way.

        True for an adoption as well as for a take, because what this
        answers is whether the proposal is still open and both close it.
        The word is the one the read side has always used for that bit
        and is left alone; which of the two closed it is the status's to
        say.

        A property rather than a stored flag, for the reason an
        execution's status is derived: a field a writer can set is a
        field a writer can set wrong, and this one cannot disagree with
        the join it reads.

        Reads `execution_id` and not `step_id`, arbitrarily, because the
        two arrive together. The root is named because it is the one a
        reader can follow on its own.
        """
        return self.execution_id is not None


__all__ = [
    "InvalidProposalParametersError",
    "Proposal",
    "ProposalAlreadyExistsError",
    "ProposalCannotBeAdoptedError",
    "ProposalCannotBeTakenError",
    "ProposalNotFoundError",
    "ProposalStatus",
]
