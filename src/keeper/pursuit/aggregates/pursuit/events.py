"""Events the Pursuit aggregate emits, and the union its evolver dispatches on.

Events live with the aggregate rather than with the slice that emits them,
because they are facts about the aggregate's history. A slice decides when
one happens; the history is not the slice's to own.

R8 runs between these, and the split is three to one. Authorizing a loop,
revoking one and opening a round are all acts performed here, so none of
their commands accepts an `occurred_at`: a speech act happens where it is
spoken and there is no earlier moment out in the world to be late to.

`PursuitCharged` is the exception and the only one that could be. What it
records is consumption measured somewhere else, by a beamline or by a
thinker counting its own tokens, and the caller was there while this
system was not. So its command takes the moment from the caller, beside
`report_step` and away from the three around it.

The budget rides as a mapping of plain strings to integers rather than as
`Budget`. That is the ordinary rule in docs/reference/modeling.md rather
than a judgement about this field: events carry primitives and the evolver
reconstructs the closed type on the way back out, which is what makes a
dimension that is no longer one of the five fail loudly at the fold instead
of spreading as a bare string.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, assert_never
from uuid import UUID

from keeper.infrastructure.ports.event_store import StoredEvent
from keeper.infrastructure.slices.payload import deserialize_or_raise


@dataclass(frozen=True)
class PursuitStarted:
    """A person authorized a bounded loop toward a goal.

    Started rather than opened, defined or created. Opening is what happens
    to an inquiry and says a thing is now awaiting an answer, which is not
    what this is. Defining is what happens to a plan and a procedure and
    says a shape was written down for later, which is also not what this
    is: a pursuit is running from the moment it exists. Started is the word
    for a loop that begins turning when you say so, and "start a pursuit"
    is the phrase somebody at a beamline would say.

    `actor_id` is whoever authorized it, which is whoever authenticated.
    The handler writes the principal into it, so a caller controls who
    authorized as exactly as much as a caller of `make_proposal` controls
    who advised. This is the field the whole aggregate is built around: a
    standing authorization whose author is not on the record is not an
    authorization.

    `beamline` and `scopes` are the two safety-bearing facts, stated once
    here so that nothing downstream has to infer them. `budget` is what
    bounds the loop, and a pursuit cannot be started without one.

    Nothing here names an execution. A pursuit is authorized before it has
    observed anything, and what it goes on to observe is its own record to
    accumulate rather than something the genesis can know.
    """

    pursuit_id: UUID
    actor_id: UUID
    goal: str
    beamline: str
    scopes: tuple[str, ...]
    budget: Mapping[str, int]
    occurred_at: datetime


@dataclass(frozen=True)
class PursuitWithdrawn:
    """A person revoked the authorization before it ran itself out.

    Withdrawn rather than stopped or cancelled. Stopped is the state rather
    than the act, and three different acts will reach it, so spending the
    word on one of them would leave the other two unnameable. Cancelled
    suggests undoing what was done, and nothing a pursuit already
    dispatched is undone by this: work already at a beamline keeps running,
    and the executions it produced stay on the record exactly as they are.

    What this ends is the authorization, not the work.

    `actor_id` is whoever withdrew it, which need not be whoever started
    it. Two different people is the ordinary case rather than the strange
    one: the person who authorizes an overnight loop is often not the
    person at the beamline when it needs stopping. Both are on the record
    and neither overwrites the other.
    """

    pursuit_id: UUID
    actor_id: UUID
    occurred_at: datetime


@dataclass(frozen=True)
class PursuitRoundOpened:
    """The pursuit asked what should run next, about one execution.

    Opened rather than asked, and the difference is what the record needs
    to be able to say. Naming this one for the asking would give a class
    that reads as the pursuit having been asked something, because every
    event in this tree is the aggregate followed by what was done to it.
    What happened is the opposite: the pursuit did the asking. So the round
    is the subject, and opening one is what the pursuit did.

    A round is the unit because the asking and the answer are separated by
    however long a thinker takes, and the thing that closes one is a
    different call than the thing that opened it. Numbering them from zero
    is what lets the second call name the first without a round needing an
    id of its own.

    `execution_id` is what this round is about. `inquiry_id` is the
    question that went with it, written on the same append, so a round
    citing a question that does not exist is not a state this can reach.

    Nothing here carries the objective. It is the pursuit's goal, unchanged
    every round, and a copy on each one would be the same sentence written
    as many times as the loop turned.
    """

    pursuit_id: UUID
    round_index: int
    execution_id: UUID
    inquiry_id: UUID
    occurred_at: datetime


@dataclass(frozen=True)
class PursuitCharged:
    """Something outside reported what this pursuit consumed.

    The one event here that describes rather than makes. Beam seconds are
    measured by whatever measures beam and tokens are counted by a thinker,
    so both arrive from a caller that was there while this system was not,
    and the command behind this one takes their moment rather than the
    clock's.

    That also means this number is only as honest as its reporter. A
    thinker that crashed before charging what it spent got it free, and
    nothing here can tell. A pursuit is a governor rather than an
    accounting system, and the two dimensions that arrive this way are why
    that sentence is worth repeating wherever they appear.

    `dimension` rides as a plain string for the reason the budget's keys
    do, and is narrowed back to the enum at the fold. Only a reported
    dimension may appear: the other three are computed from this
    aggregate's own history, so a charge against one would be counted
    twice, and the decider refuses it.

    Charges accumulate rather than replace. A reporter sending what one
    round spent does not have to know what every round before it spent,
    which is what lets a thinker charge its own tokens without reading the
    pursuit first.
    """

    pursuit_id: UUID
    dimension: str
    amount: int
    occurred_at: datetime


@dataclass(frozen=True)
class PursuitRoundClosed:
    """The answer came back, and the round ended one of four ways.

    One class with an outcome rather than four classes, which is the choice
    `InquiryConclusion` makes and for its stated reason: these four arrive
    from one call and three of them carry nothing beyond the round they
    closed, so the difference between them is one bit rather than four
    shapes. Four classes earn their place where four payloads differ, which
    is why an execution's step outcomes are four and these are not.

    `outcome` rides as a plain string and is narrowed back at the fold,
    which is the ordinary rule for a closed type on a payload.

    `proposal_id` and `dispatched_id` are set on the advancing outcome and
    on no other. They are the two halves of one fact, the advice taken up
    and the work it became, and the decider refuses either without the
    other. That is the one thing this event could carry wrongly.

    Closing is an act performed here: the caller is telling this system to
    read an answer already on the record and act on it, and the moment this
    system acts is the moment it happened. So the command behind this
    accepts no timestamp, beside the three around it and away from the
    charge.
    """

    pursuit_id: UUID
    round_index: int
    outcome: str
    proposal_id: UUID | None
    dispatched_id: UUID | None
    occurred_at: datetime


@dataclass(frozen=True)
class PursuitResumed:
    """A person put a held pursuit back to work.

    The counterpart to the two outcomes that hold rather than stop. A
    thinker with nothing to go on and a thinker asking for a person are
    both answerable: more data may land, and whoever was referred to can
    look. Neither is a reason to throw the authorization away, so neither
    does, and this is how one comes back.

    `actor_id` is whoever resumed it, which need not be whoever authorized
    it or whoever the referral was aimed at. A pursuit may be held and
    resumed many times, and each is its own row, so the record keeps the
    whole sequence rather than a flag that only remembers the last one.

    Nothing about the hold is repeated here. Which round held it and why
    are on the round, and a copy would be a second account of one fact.
    """

    pursuit_id: UUID
    actor_id: UUID
    occurred_at: datetime


PursuitEvent = (
    PursuitStarted
    | PursuitRoundOpened
    | PursuitRoundClosed
    | PursuitCharged
    | PursuitResumed
    | PursuitWithdrawn
)
"""Every event that can appear on a Pursuit stream.

A new member is a new class added here and to this alias, never a field
bolted onto an event already in the log. Adding one without teaching the
evolver about it is a type error, because the wildcard arm there calls
`assert_never`.
"""


def to_payload(event: PursuitEvent) -> dict[str, Any]:
    """Render an event as the primitives that get stored."""
    match event:
        case PursuitStarted():
            return {
                "pursuit_id": str(event.pursuit_id),
                "actor_id": str(event.actor_id),
                "goal": event.goal,
                "beamline": event.beamline,
                "scopes": list(event.scopes),
                "budget": dict(event.budget),
                "occurred_at": event.occurred_at.isoformat(),
            }
        case PursuitRoundOpened():
            return {
                "pursuit_id": str(event.pursuit_id),
                "round_index": event.round_index,
                "execution_id": str(event.execution_id),
                "inquiry_id": str(event.inquiry_id),
                "occurred_at": event.occurred_at.isoformat(),
            }
        case PursuitRoundClosed():
            return {
                "pursuit_id": str(event.pursuit_id),
                "round_index": event.round_index,
                "outcome": event.outcome,
                "proposal_id": None if event.proposal_id is None else str(event.proposal_id),
                "dispatched_id": (
                    None if event.dispatched_id is None else str(event.dispatched_id)
                ),
                "occurred_at": event.occurred_at.isoformat(),
            }
        case PursuitResumed():
            return {
                "pursuit_id": str(event.pursuit_id),
                "actor_id": str(event.actor_id),
                "occurred_at": event.occurred_at.isoformat(),
            }
        case PursuitCharged():
            return {
                "pursuit_id": str(event.pursuit_id),
                "dimension": event.dimension,
                "amount": event.amount,
                "occurred_at": event.occurred_at.isoformat(),
            }
        case PursuitWithdrawn():
            return {
                "pursuit_id": str(event.pursuit_id),
                "actor_id": str(event.actor_id),
                "occurred_at": event.occurred_at.isoformat(),
            }
        case _:
            assert_never(event)


def from_stored(stored: StoredEvent) -> PursuitEvent:
    """Rebuild an event from its stored row.

    `extra` carries `ValueError` because the constructors below raise it on
    malformed input: strings that are not UUIDs, and one that is not a
    timestamp. Without it those escape as themselves, naming the field
    rather than the event.

    Neither the budget's dimensions nor its limits are narrowed here. A
    dimension that is no longer one of the five, and a limit that is no
    longer positive, both fail when the evolver reconstructs `Budget`,
    which is where every other payload value in this tree is re-validated.
    """
    payload = stored.payload
    match stored.event_type:
        case "PursuitStarted":
            return deserialize_or_raise(
                "PursuitStarted",
                lambda: PursuitStarted(
                    pursuit_id=UUID(payload["pursuit_id"]),
                    actor_id=UUID(payload["actor_id"]),
                    goal=str(payload["goal"]),
                    beamline=str(payload["beamline"]),
                    scopes=tuple(str(scope) for scope in payload["scopes"]),
                    budget={
                        str(name): int(limit) for name, limit in dict(payload["budget"]).items()
                    },
                    occurred_at=datetime.fromisoformat(payload["occurred_at"]),
                ),
                extra=(ValueError,),
            )
        case "PursuitRoundOpened":
            return deserialize_or_raise(
                "PursuitRoundOpened",
                lambda: PursuitRoundOpened(
                    pursuit_id=UUID(payload["pursuit_id"]),
                    round_index=int(payload["round_index"]),
                    execution_id=UUID(payload["execution_id"]),
                    inquiry_id=UUID(payload["inquiry_id"]),
                    occurred_at=datetime.fromisoformat(payload["occurred_at"]),
                ),
                extra=(ValueError,),
            )
        case "PursuitRoundClosed":
            return deserialize_or_raise(
                "PursuitRoundClosed",
                lambda: PursuitRoundClosed(
                    pursuit_id=UUID(payload["pursuit_id"]),
                    round_index=int(payload["round_index"]),
                    outcome=str(payload["outcome"]),
                    proposal_id=(
                        None if payload["proposal_id"] is None else UUID(payload["proposal_id"])
                    ),
                    dispatched_id=(
                        None if payload["dispatched_id"] is None else UUID(payload["dispatched_id"])
                    ),
                    occurred_at=datetime.fromisoformat(payload["occurred_at"]),
                ),
                extra=(ValueError,),
            )
        case "PursuitResumed":
            return deserialize_or_raise(
                "PursuitResumed",
                lambda: PursuitResumed(
                    pursuit_id=UUID(payload["pursuit_id"]),
                    actor_id=UUID(payload["actor_id"]),
                    occurred_at=datetime.fromisoformat(payload["occurred_at"]),
                ),
                extra=(ValueError,),
            )
        case "PursuitCharged":
            return deserialize_or_raise(
                "PursuitCharged",
                lambda: PursuitCharged(
                    pursuit_id=UUID(payload["pursuit_id"]),
                    dimension=str(payload["dimension"]),
                    amount=int(payload["amount"]),
                    occurred_at=datetime.fromisoformat(payload["occurred_at"]),
                ),
                extra=(ValueError,),
            )
        case "PursuitWithdrawn":
            return deserialize_or_raise(
                "PursuitWithdrawn",
                lambda: PursuitWithdrawn(
                    pursuit_id=UUID(payload["pursuit_id"]),
                    actor_id=UUID(payload["actor_id"]),
                    occurred_at=datetime.fromisoformat(payload["occurred_at"]),
                ),
                extra=(ValueError,),
            )
        case unknown:
            msg = f"Unknown Pursuit event_type: {unknown!r}"
            raise ValueError(msg)


__all__ = [
    "PursuitCharged",
    "PursuitEvent",
    "PursuitResumed",
    "PursuitRoundClosed",
    "PursuitRoundOpened",
    "PursuitStarted",
    "PursuitWithdrawn",
    "from_stored",
    "to_payload",
]
