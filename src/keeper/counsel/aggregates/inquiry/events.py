"""Events the Inquiry aggregate emits, and the union its evolver dispatches on.

Events live with the aggregate rather than with the slice that emits them,
because they are facts about the aggregate's history. A slice decides when
one happens; the history is not the slice's to own.

Three members, and R8 runs between them the way it runs between this
context's other two. `InquiryMade` records an act performed here, so the
command that produces it accepts no timestamp. `InquiryClaimed` and
`InquiryAnswered` both record something a thinker did on its own clock
somewhere else, so both of their commands accept one.

All three carry `occurred_at` all the same. Every event does: what differs
is who is allowed to say what it holds.

`conclusion` rides as a plain string rather than as `InquiryConclusion`.
That is the ordinary rule in docs/reference/modeling.md rather than a
judgement about this field: events carry primitives and the evolver
reconstructs the closed type on the way back out, which is what makes a
value that has gone out of range fail loudly at the fold instead of
spreading as a bare string.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, assert_never
from uuid import UUID

from keeper.infrastructure.ports.event_store import StoredEvent
from keeper.infrastructure.slices.payload import deserialize_or_raise


@dataclass(frozen=True)
class InquiryMade:
    """An actor put a question to a thinker.

    Made rather than opened or registered, and it is `ProposalMade`'s word
    for `ProposalMade`'s reason. Asking is an act, acts are authored by
    being performed, and "make an inquiry" is the phrase people say. Opening
    one would have been the investigation sense of the word, which is the
    sense this context does not mean.

    This system is the authority for the fact. Putting a question is a
    speech act and the call is where it was spoken, so there is no earlier
    moment out in the world for the record to be late to. That is why the
    command behind this event accepts no `occurred_at`, beside
    `make_proposal` and away from the two that follow it here.

    `actor_id` is whoever asked, which is whoever authenticated. The handler
    writes the principal into it, so a caller controls who it asked as
    exactly as much as a caller of `make_proposal` controls who advised.

    `execution_step_count` is captured from the execution the handler
    loaded, not taken from the caller. It is the denominator the answer's
    observation boundary is read against, and a caller that supplied its own
    could make a partial reading look complete.

    Nothing here carries the case. The whole of what a thinker will read is
    reachable through `execution_id`, and copying any of it would put a
    second account of one execution in a table nobody can edit afterwards.
    """

    inquiry_id: UUID
    actor_id: UUID
    execution_id: UUID
    objective: str
    execution_step_count: int
    occurred_at: datetime


@dataclass(frozen=True)
class InquiryClaimed:
    """A thinker said it has taken this question up.

    Claim, and not start, which is `ClaimExecution`'s distinction and holds
    for the same reason: starting would say something has been concluded,
    and nothing has. This says only that a question sitting unanswered has
    been picked up.

    No field naming the claimant. The envelope carries the principal that
    issued the command, and a second copy on the payload could disagree with
    it.

    Nothing here stops two thinkers reading one execution, and nothing
    could: a claim is a record, not a lock. What it does is keep the
    disagreement in the log rather than only in somebody's inference bill.
    """

    inquiry_id: UUID
    occurred_at: datetime


@dataclass(frozen=True)
class InquiryAnswered:
    """A thinker concluded something, and said how much it had seen.

    Answered rather than concluded, and the word left alone is the point.
    `conclusion` is what the thinker reached, and an event that spelled its
    own name with the same word would spend it twice, leaving a reader
    unable to tell the arrival of an answer from the answer itself.

    The thinking happened in a thinker, over a model this system never saw,
    so this event describes an act rather than making one and its command
    takes an `occurred_at`.

    `observed_step_count` and `execution_ended` are the observation
    boundary, and both are the thinker's own account. Nothing here can check
    them: by the time this arrives the execution has moved on, so the
    reading they describe is gone. What the decider can check is that they
    are not impossible, and it does.

    They are two facts rather than one because they answer two questions. An
    execution can be closed with steps nobody reported on, and one with an
    outcome against every step has not necessarily been closed.

    `proposal_id` is set when the conclusion is `Propose` and is None
    otherwise. The proposal is written first, on its own stream, and this
    cites it: a crash between the two leaves a proposal that reads as any
    other actor's, which is the harmless direction to fail in.
    """

    inquiry_id: UUID
    conclusion: str
    observed_step_count: int
    execution_ended: bool
    proposal_id: UUID | None
    occurred_at: datetime


InquiryEvent = InquiryMade | InquiryClaimed | InquiryAnswered
"""Every event that can appear on an Inquiry stream.

A new member is a new class added here and to this alias, never a field
bolted onto an event already in the log. Withdrawing a question nobody
answered is the foreseeable one. Adding one without teaching the evolver
about it is a type error, because the wildcard arm there calls
`assert_never`.
"""


def to_payload(event: InquiryEvent) -> dict[str, Any]:
    """Render an event as the primitives that get stored."""
    match event:
        case InquiryMade():
            return {
                "inquiry_id": str(event.inquiry_id),
                "actor_id": str(event.actor_id),
                "execution_id": str(event.execution_id),
                "objective": event.objective,
                "execution_step_count": event.execution_step_count,
                "occurred_at": event.occurred_at.isoformat(),
            }
        case InquiryClaimed():
            return {
                "inquiry_id": str(event.inquiry_id),
                "occurred_at": event.occurred_at.isoformat(),
            }
        case InquiryAnswered():
            return {
                "inquiry_id": str(event.inquiry_id),
                "conclusion": event.conclusion,
                "observed_step_count": event.observed_step_count,
                "execution_ended": event.execution_ended,
                "proposal_id": None if event.proposal_id is None else str(event.proposal_id),
                "occurred_at": event.occurred_at.isoformat(),
            }
        case _:
            assert_never(event)


def from_stored(stored: StoredEvent) -> InquiryEvent:
    """Rebuild an event from its stored row.

    `extra` carries `ValueError` because the constructors below raise it on
    malformed input: strings that are not UUIDs, and one that is not a
    timestamp. Without it those escape as themselves, naming the field
    rather than the event.

    The conclusion is not narrowed here. A string that is no longer one of
    the four fails when the evolver reconstructs it, which is where every
    other payload value in this tree is re-validated.
    """
    payload = stored.payload
    match stored.event_type:
        case "InquiryMade":
            return deserialize_or_raise(
                "InquiryMade",
                lambda: InquiryMade(
                    inquiry_id=UUID(payload["inquiry_id"]),
                    actor_id=UUID(payload["actor_id"]),
                    execution_id=UUID(payload["execution_id"]),
                    objective=str(payload["objective"]),
                    execution_step_count=int(payload["execution_step_count"]),
                    occurred_at=datetime.fromisoformat(payload["occurred_at"]),
                ),
                extra=(ValueError,),
            )
        case "InquiryClaimed":
            return deserialize_or_raise(
                "InquiryClaimed",
                lambda: InquiryClaimed(
                    inquiry_id=UUID(payload["inquiry_id"]),
                    occurred_at=datetime.fromisoformat(payload["occurred_at"]),
                ),
                extra=(ValueError,),
            )
        case "InquiryAnswered":
            return deserialize_or_raise(
                "InquiryAnswered",
                lambda: InquiryAnswered(
                    inquiry_id=UUID(payload["inquiry_id"]),
                    conclusion=str(payload["conclusion"]),
                    observed_step_count=int(payload["observed_step_count"]),
                    execution_ended=bool(payload["execution_ended"]),
                    proposal_id=(
                        None if payload["proposal_id"] is None else UUID(payload["proposal_id"])
                    ),
                    occurred_at=datetime.fromisoformat(payload["occurred_at"]),
                ),
                extra=(ValueError,),
            )
        case unknown:
            msg = f"Unknown Inquiry event_type: {unknown!r}"
            raise ValueError(msg)


__all__ = [
    "InquiryAnswered",
    "InquiryClaimed",
    "InquiryEvent",
    "InquiryMade",
    "from_stored",
    "to_payload",
]
