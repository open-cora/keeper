"""Replay Proposal events to reconstruct current state.

`evolve` applies one event. `fold` walks a whole stream from the empty
state, which is what the read path calls after loading rows.

Both are pure and total: the same events in the same order always give
the same state, on any machine, years apart. That is the property the
whole approach rests on, and it is why nothing here reads a clock, a
config value or a database.

The wildcard arm calls `assert_never`, so adding an event class to the
union without handling it here is a type error rather than a state that
silently comes back as None.
"""

from collections.abc import Sequence
from dataclasses import replace
from typing import assert_never

from keeper.counsel.aggregates.proposal.events import (
    ProposalAdopted,
    ProposalEvent,
    ProposalMade,
    ProposalTaken,
)
from keeper.counsel.aggregates.proposal.state import Proposal, ProposalStatus
from keeper.infrastructure.slices.evolver import require_state


def evolve(state: Proposal | None, event: ProposalEvent) -> Proposal:
    """Apply one event to the state before it.

    The genesis arm builds the proposal and ignores the prior state,
    which must be None. The other two require one, because neither a
    step that ran what was proposed nor a decision to run it can happen
    to a proposal that was never made.

    The two closing arms write the same two ids and differ only in the
    status they leave behind, which is the whole of what separates an
    adoption from a take on the read side. The status is set by which
    arm ran and is never read off a payload, so it cannot contradict the
    event that produced it.

    `parameters` is shallow-copied out of the payload rather than
    aliased. The fold would otherwise share one dict between the event
    and the state it built, where mutating either silently changes the
    other. That is the companion defence
    docs/reference/modeling.md asks for at every dict-typed payload
    field, since the fitness test that pins immutable collections cannot
    pin a freeform document.
    """
    match event:
        case ProposalMade(
            proposal_id=proposal_id,
            actor_id=actor_id,
            operation_id=operation_id,
            parameters=parameters,
        ):
            _ = state
            return Proposal(
                id=proposal_id,
                actor_id=actor_id,
                operation_id=operation_id,
                parameters=dict(parameters),
                status=ProposalStatus.OPEN,
                execution_id=None,
                step_id=None,
            )
        case ProposalTaken(execution_id=execution_id, step_id=step_id):
            return replace(
                require_state(state, "ProposalTaken"),
                status=ProposalStatus.TAKEN,
                execution_id=execution_id,
                step_id=step_id,
            )
        case ProposalAdopted(execution_id=execution_id, step_id=step_id):
            return replace(
                require_state(state, "ProposalAdopted"),
                status=ProposalStatus.ADOPTED,
                execution_id=execution_id,
                step_id=step_id,
            )
        case _:
            assert_never(event)


def fold(events: Sequence[ProposalEvent]) -> Proposal | None:
    """Replay a stream from the empty state. None means no events at all.

    Takes a `Sequence` rather than a `list` so a caller holding a list of
    one concrete event type can pass it without a cast, which is most
    callers in tests.
    """
    state: Proposal | None = None
    for event in events:
        state = evolve(state, event)
    return state


__all__ = ["evolve", "fold"]
