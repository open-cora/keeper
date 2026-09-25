"""The decision: what taking a proposal produces.

Update-style, so the state comes in already folded and `new_id` is
absent: this command names its stream rather than creating one.

Pure. No awaits, no ports, no clock.
"""

from datetime import datetime

from keeper.counsel.aggregates.proposal import (
    Proposal,
    ProposalCannotBeTakenError,
    ProposalNotFoundError,
    ProposalTaken,
)
from keeper.counsel.features.take_proposal.command import TakeProposal
from keeper.counsel.features.take_proposal.context import TakeProposalContext
from keeper.execution.aggregates.procedure import runs_plan


def decide(
    state: Proposal | None,
    command: TakeProposal,
    *,
    context: TakeProposalContext,
    now: datetime,
) -> list[ProposalTaken]:
    """Decide the events produced by taking a proposal.

    Invariants:
      - State must not be None, or no such proposal was made
        -> ProposalNotFoundError
      - The proposal must not already have a step against it
        -> ProposalCannotBeTakenError
      - The step's definition must run a plan at all, rather than being
        a move -> ProposalCannotBeTakenError
      - That plan must be the one the proposal names
        -> ProposalCannotBeTakenError

    **Taking one twice is refused, and that is a domain claim rather
    than a safety rail.** A rerun after a failure is a new proposal,
    because the second run was chosen after seeing the first one fail,
    and that is a second choice. Refusing is also the reversible
    direction: allowing it later costs a sentence, and disallowing it
    later costs a migration.

    **A move is refused before the plans are compared**, and the order
    matters to what the caller is told. A move runs no plan, so a single
    comparison would refuse it anyway, with a message saying the step
    ran a different plan and naming none. That reads as a near miss and
    sends a caller looking for the right acquisition, when what it has
    is a step that could never take a proposal at all.

    **The plan is compared and the parameters are not.** Comparing the
    plan is the cheap guard against citing a step from the wrong
    execution, which is easy to do when one procedure is dispatched many
    times over. Comparing parameters would not be: an engine normalizes
    values and fills defaults, so what a step was dispatched with can
    differ from what was proposed while still being the acquisition that
    was proposed, and a dict comparison would refuse legitimate joins to
    catch a case nobody has seen.

    All three refusals share a class and a status, because the caller's
    next move is the same in kind: stop, and work out which step it
    meant. The error carries what tells them apart.

    **The plan is read off the procedure, not off the execution.** An
    execution's step says which composed step it was dispatched from and
    the composed step says what it does, so `runs_plan` is asked the same
    question here that it is asked at dispatch. The step id in the
    refusals is still the execution's, because that is what the caller
    sent and what it has to go and fix.
    """
    if state is None:
        raise ProposalNotFoundError(command.proposal_id)
    if state.step_id is not None:
        raise ProposalCannotBeTakenError.already_taken(state.id, state.step_id)
    step_plan_id = runs_plan(context.composed.step)
    if step_plan_id is None:
        raise ProposalCannotBeTakenError.not_an_acquisition(state.id, command.step_id)
    if step_plan_id != state.plan_id:
        raise ProposalCannotBeTakenError.plan_mismatch(
            state.id,
            proposed_plan_id=state.plan_id,
            step_plan_id=step_plan_id,
        )
    return [
        ProposalTaken(
            proposal_id=command.proposal_id,
            execution_id=command.execution_id,
            step_id=command.step_id,
            occurred_at=now,
        )
    ]


__all__ = ["decide"]
