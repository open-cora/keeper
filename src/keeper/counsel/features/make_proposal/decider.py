"""The decision: what making a proposal produces.

Pure. No awaits, no ports, no clock. `now` and `new_id` arrive as
parameters, and the plan arrives on the context, precisely so this
function has nothing to fetch and nothing to invent.

`actor_id` arrives as a parameter rather than on the command, because it
is not the caller's to set. The handler reads it off the authenticated
principal and passes it in, which keeps the decision a function of its
inputs while leaving the caller no way to advise as somebody else.
"""

from datetime import datetime
from uuid import UUID

from keeper.counsel.aggregates.proposal import (
    InvalidProposalParametersError,
    Proposal,
    ProposalAlreadyExistsError,
    ProposalMade,
)
from keeper.counsel.features.make_proposal.command import MakeProposal
from keeper.counsel.features.make_proposal.context import MakeProposalContext
from keeper.shared.json_schema.validation import validate_values_against_schema


def decide(
    state: Proposal | None,
    command: MakeProposal,
    *,
    context: MakeProposalContext,
    actor_id: UUID,
    now: datetime,
    new_id: UUID,
) -> list[ProposalMade]:
    """Decide the events produced by making a proposal.

    Invariants:
      - State must be None, or the id already has a history
        -> ProposalAlreadyExistsError
      - The values must satisfy the plan's declared schema
        -> InvalidProposalParametersError

    The second is what makes this a proposal rather than a wish. Values
    that could not be run are not a run put forward, and checking them
    here means a proposer learns at the moment it advises rather than
    when somebody tries to act on it.

    The handler has already refused a plan id with no stream behind it,
    so by the time the context is built the plan exists. Existence is the
    handler's to check and state is the decider's, which is the split
    docs/reference/patterns.md draws between a 404 and a refusal.

    `no_schema_message` is not passed, so the shared validator runs in
    its relaxed posture, and the choice does not matter here: a plan
    cannot be defined without a schema, so the absent-schema case the
    argument exists for cannot arise.

    What is NOT checked is anything about other proposals. Nothing here
    can see another stream, so two agents proposing the same run make
    two proposals and nothing notices. That is the intended reading
    rather than a gap: two agents advising the same thing is two pieces
    of advice.
    """
    if state is not None:
        raise ProposalAlreadyExistsError(state.id)
    validate_values_against_schema(
        command.parameters,
        context.plan.parameters_schema,
        error_class=InvalidProposalParametersError,
    )
    return [
        ProposalMade(
            proposal_id=new_id,
            actor_id=actor_id,
            plan_id=command.plan_id,
            parameters=command.parameters,
            occurred_at=now,
        )
    ]


__all__ = ["decide"]
