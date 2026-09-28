"""The decision: what adopting a proposal produces, on this stream.

Update-style, so the state comes in already folded and `new_id` is
absent: this command names its stream rather than creating one.

**It decides one of the three events the slice writes.** The procedure
and the execution are Execution's to decide, and its own deciders are
called for them, so this function's whole job is the arm that belongs to
the proposal. That split is what keeps the decision about a procedure in
the context that owns procedures while the write stays in one
transaction.

Pure. No awaits, no ports, no clock.
"""

from datetime import datetime
from uuid import UUID

from keeper.counsel.aggregates.proposal import (
    Proposal,
    ProposalAdopted,
    ProposalCannotBeAdoptedError,
    ProposalNotFoundError,
    ProposalStatus,
)
from keeper.counsel.features.adopt_proposal.command import AdoptProposal


def decide(
    state: Proposal | None,
    command: AdoptProposal,
    *,
    execution_id: UUID,
    step_id: UUID,
    now: datetime,
) -> list[ProposalAdopted]:
    """Decide the events produced by adopting a proposal.

    Invariants:
      - State must not be None, or no such proposal was made
        -> ProposalNotFoundError
      - The proposal must still be open
        -> ProposalCannotBeAdoptedError

    Refused from both of the closed statuses and they mean different
    things, which is why the error carries which one it met. Adopting
    something already adopted is a second commitment of the facility to
    one piece of advice. Adopting something already taken is advice
    something else has acted on, where composing more work would run it
    twice.

    **Neither the beamline nor the scopes are checked here.** Both are
    Execution's to refuse and it does: a beamline outside its bound and
    a run declaring no devices are each already a refusal in
    `define_procedure`, raised before this function is reached. Checking
    them again would be this context holding an opinion about a bound
    that another context enforces, and the two would drift.

    `execution_id` and `step_id` arrive as parameters rather than on the
    command, because they are not the caller's: they were minted by the
    handler's ports moments earlier and belong to records this same
    transaction is creating.
    """
    if state is None:
        raise ProposalNotFoundError(command.proposal_id)
    if state.status is not ProposalStatus.OPEN:
        raise ProposalCannotBeAdoptedError(state.id, state.status)
    return [
        ProposalAdopted(
            proposal_id=command.proposal_id,
            execution_id=execution_id,
            step_id=step_id,
            occurred_at=now,
        )
    ]


__all__ = ["decide"]
