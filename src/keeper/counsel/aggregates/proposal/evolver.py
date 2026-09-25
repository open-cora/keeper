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
    ProposalEvent,
    ProposalMade,
    ProposalTaken,
)
from keeper.counsel.aggregates.proposal.state import Proposal
from keeper.infrastructure.slices.evolver import require_state


def evolve(state: Proposal | None, event: ProposalEvent) -> Proposal:
    """Apply one event to the state before it.

    The genesis arm builds the proposal and ignores the prior state,
    which must be None. The second arm requires one, because an
    acquisition cannot be recorded against a proposal that was never
    made.

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
            plan_id=plan_id,
            parameters=parameters,
        ):
            _ = state
            return Proposal(
                id=proposal_id,
                actor_id=actor_id,
                plan_id=plan_id,
                parameters=dict(parameters),
                execution_id=None,
                step_id=None,
            )
        case ProposalTaken(execution_id=execution_id, step_id=step_id):
            return replace(
                require_state(state, "ProposalTaken"),
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
