"""Replay Inquiry events to reconstruct current state.

`evolve` applies one event. `fold` walks a whole stream from the empty
state, which is what the read path calls after loading rows.

Both are pure and total: the same events in the same order always give the
same state, on any machine, years apart. That is the property the whole
approach rests on, and it is why nothing here reads a clock, a config value
or a database.

The wildcard arm calls `assert_never`, so adding an event class to the union
without handling it here is a type error rather than a state that silently
comes back as None.
"""

from collections.abc import Sequence
from dataclasses import replace
from typing import assert_never

from keeper.counsel.aggregates.inquiry.events import (
    InquiryAnswered,
    InquiryClaimed,
    InquiryEvent,
    InquiryMade,
)
from keeper.counsel.aggregates.inquiry.state import (
    Inquiry,
    InquiryConclusion,
    InquiryObjective,
    InquiryStatus,
)
from keeper.infrastructure.slices.evolver import require_state


def evolve(state: Inquiry | None, event: InquiryEvent) -> Inquiry:
    """Apply one event to the state before it.

    The genesis arm builds the inquiry and ignores the prior state, which
    must be None. The other two require one, because neither taking a
    question up nor answering it can happen to a question nobody asked.

    Both closed types are reconstructed rather than carried across as the
    strings the payload holds. That is what re-validates them on read: an
    objective that has outgrown its bound and a conclusion that is no longer
    one of the four both fail here, at the fold, rather than reaching a
    caller as a string nothing checked.

    The status is set by which arm ran and is never read off a payload, so
    it cannot contradict the event that produced it.
    """
    match event:
        case InquiryMade(
            inquiry_id=inquiry_id,
            actor_id=actor_id,
            execution_id=execution_id,
            objective=objective,
            execution_step_count=execution_step_count,
        ):
            _ = state
            return Inquiry(
                id=inquiry_id,
                actor_id=actor_id,
                execution_id=execution_id,
                objective=InquiryObjective(objective),
                execution_step_count=execution_step_count,
                status=InquiryStatus.OPEN,
            )
        case InquiryClaimed():
            return replace(
                require_state(state, "InquiryClaimed"),
                status=InquiryStatus.CLAIMED,
            )
        case InquiryAnswered(
            conclusion=conclusion,
            observed_step_count=observed_step_count,
            execution_ended=execution_ended,
            proposal_id=proposal_id,
        ):
            return replace(
                require_state(state, "InquiryAnswered"),
                status=InquiryStatus.ANSWERED,
                conclusion=InquiryConclusion(conclusion),
                observed_step_count=observed_step_count,
                execution_ended=execution_ended,
                proposal_id=proposal_id,
            )
        case _:
            assert_never(event)


def fold(events: Sequence[InquiryEvent]) -> Inquiry | None:
    """Replay a stream from the empty state. None means no events at all.

    Takes a `Sequence` rather than a `list` so a caller holding a list of
    one concrete event type can pass it without a cast, which is most
    callers in tests.
    """
    state: Inquiry | None = None
    for event in events:
        state = evolve(state, event)
    return state


__all__ = ["evolve", "fold"]
