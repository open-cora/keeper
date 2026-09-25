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

It cites a plan, it does not contain one, which is the posture every
record in this tree that names a plan takes for the same reason: the
plan is a record on another stream, and a copy here would go stale the
first time somebody defined a new one.

That leaves a proposal carrying what an acquisition step carries, and
the difference between them is that one happened. An acquisition is a
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

## Why there is no status field

`execution_id is None` is the whole of it. An execution derives a
four-valued status in its fold because no single field carries it; here
a two-valued enum beside a nullable field would be the same fact written
twice.

An enum arrives at the third state. Withdrawing and superseding are the
two candidates, and the first to land is what stops the answer being
readable off one field.

Open is the honest default and stays honest the way Dispatched does: it
says only that nothing has been recorded against this proposal. A
proposal nobody acted on reads as open forever, and closing that needs
something watching rather than another value.
"""

from dataclasses import dataclass
from typing import Any
from uuid import UUID


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
    """The proposed values do not satisfy the plan's declared schema.

    A proposal that could not be run is not a proposal, so the values
    are checked against the same schema, by the same shared validator,
    that checks an acquisition's. Its own class rather than Execution's,
    because the two are refused on different surfaces and a caller
    reading `InvalidProcedureParametersError` from a proposal endpoint
    would go looking for a procedure.
    """


class ProposalCannotBeTakenError(Exception):
    """An acquisition cannot be recorded against this proposal.

    Three causes, one class, which is the shape
    `ExecutionCannotBeClaimedError` also takes: one verb, more than one
    way to be refused, and the discriminating state carried on the error
    rather than split across class names. R6 is about not collapsing
    several VERBS into one class, and there is one verb here.

    The causes are told apart by which attribute is set. `taken_by` set
    means the proposal already has a step against it. `step_plan_id` set
    means the cited step ran a different plan from the one proposed, and
    the two plan ids say which. Neither set means the cited step runs no
    plan at all, which is a move.

    The third cause arrived with the step reference and is genuinely
    distinct rather than a mismatch against nothing. A mismatch tells a
    caller it resolved the wrong acquisition; this tells it that what it
    resolved is not an acquisition, so the fix is not to go looking for
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
        proposed_plan_id: UUID | None = None,
        step_plan_id: UUID | None = None,
    ) -> None:
        super().__init__(f"Proposal {proposal_id} cannot be taken: {detail}")
        self.proposal_id = proposal_id
        self.taken_by = taken_by
        self.proposed_plan_id = proposed_plan_id
        self.step_plan_id = step_plan_id

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
        cls, proposal_id: UUID, *, proposed_plan_id: UUID, step_plan_id: UUID
    ) -> "ProposalCannotBeTakenError":
        """The cited acquisition ran a different plan from the one proposed."""
        return cls(
            proposal_id,
            f"it proposes plan {proposed_plan_id} and the step ran plan {step_plan_id}",
            proposed_plan_id=proposed_plan_id,
            step_plan_id=step_plan_id,
        )

    @classmethod
    def not_an_acquisition(cls, proposal_id: UUID, step_id: UUID) -> "ProposalCannotBeTakenError":
        """The cited step runs no plan, so it cannot have run this one.

        A move, today. What makes this refusable rather than merely
        false is that a proposal proposes running a plan, and a step
        that hands nothing to an engine has not run one whatever else it
        did.
        """
        return cls(
            proposal_id,
            f"step {step_id} runs no plan, and a proposal proposes running one",
        )


@dataclass(frozen=True)
class Proposal:
    """A run an actor put forward, as the fold leaves it.

    `actor_id` is whoever proposed, written by the handler from the
    authenticated principal rather than supplied by the caller. It
    duplicates the envelope's `principal_id` on purpose: the envelope is
    infrastructure and the fold never sees it, and who advised is a
    domain question that should be answerable from the domain record.

    Named for the aggregate it points at, the way `plan_id` is. The role
    it plays is carried by the record it sits on rather than by a second
    word in the field name.

    `execution_id` and `step_id` are None until an acquisition is
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
    plan_id: UUID
    parameters: dict[str, Any]
    execution_id: UUID | None = None
    step_id: UUID | None = None

    @property
    def is_taken(self) -> bool:
        """Whether an acquisition has been recorded against this proposal.

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
    "ProposalCannotBeTakenError",
    "ProposalNotFoundError",
]
