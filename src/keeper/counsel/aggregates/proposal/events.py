"""Events the Proposal aggregate emits, and the union its evolver dispatches on.

Events live with the aggregate rather than with the slice that emits
them, because they are facts about the aggregate's history. A slice
decides when one happens; the history is not the slice's to own.

Two members, and between them they carry the whole of R8. `ProposalMade`
records an act performed here, so the command that produces it accepts
no timestamp and the handler supplies the clock's reading.
`ProposalTaken` records a step that was driven somewhere else, so its
command does accept one. Everywhere else in this tree that split runs between
contexts; here it runs between two commands on one stream.

Both carry `occurred_at` all the same. Every event does: what differs is
who is allowed to say what it holds.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, assert_never
from uuid import UUID

from keeper.infrastructure.ports.event_store import StoredEvent
from keeper.infrastructure.slices.payload import deserialize_or_raise


@dataclass(frozen=True)
class ProposalMade:
    """An actor put a run forward.

    Made rather than defined or registered, and neither of the glossary's
    two genesis words fits. "Define a proposal" sounds like settling what
    the word means, and "register a proposal" says it came from somewhere
    else. That pair was built for things that persist as specifications,
    a plan or a policy, and a proposal is an act. Acts are authored by
    being performed, so the genesis takes the natural verb of the act.

    This system is the authority for the fact. Proposing is a speech act
    and the call is where it was spoken, so there is no earlier moment
    out in the world for the record to be late to. That is why the
    command behind this event accepts no `occurred_at` where
    `register_dataset` next door does.

    `actor_id` is whoever proposed, which is whoever authenticated. The
    handler writes the principal into it, so a caller controls who it
    proposed as exactly as much as a caller of `register_actor` controls
    the new actor's id. A person and a piece of software make the same
    record here, and nothing on it says which this was.

    Nothing here carries a reason, a goal or a confidence. A proposer's
    rationale is unbounded free text that will eventually quote a person,
    and this table cannot be edited afterwards. `ActorDeactivated`
    carries no reason for the same reason.
    """

    proposal_id: UUID
    actor_id: UUID
    plan_id: UUID
    parameters: dict[str, Any]
    occurred_at: datetime


@dataclass(frozen=True)
class ProposalTaken:
    """An acquisition was recorded against a proposal.

    Taken rather than accepted, and the word withheld is the point.
    Accepting says a party considered the proposal and said yes. Nobody
    did: this event records that a step exists that ran what the
    proposal proposed, and whoever composed the procedure holding that
    step may simply have gone ahead. Claiming an approval that did not
    happen is what got "witnessed" thrown out of Execution.

    The accepted spelling is also reserved rather than merely unused.
    Approval by a person is a real future event on this stream, distinct
    from and prior to anything running, because an operator can approve
    something that then never runs, and spending the word here would
    leave that event nothing to be called.

    Carries both ids because a step is an entity inside an execution
    rather than a stream of its own, so the step id alone names
    something no reader can reach.

    No actor. On the genesis the principal is the substance of the fact;
    here the caller is a messenger and the acquisition is the fact.
    """

    proposal_id: UUID
    execution_id: UUID
    step_id: UUID
    occurred_at: datetime


ProposalEvent = ProposalMade | ProposalTaken
"""Every event that can appear on a Proposal stream.

A new member is a new class added here and to this alias, never a field
bolted onto an event already in the log. Withdrawing and superseding are
the two foreseeable ones. Adding one without teaching the evolver about
it is a type error, because the wildcard arm there calls `assert_never`.
"""


def to_payload(event: ProposalEvent) -> dict[str, Any]:
    """Render an event as the primitives that get stored."""
    match event:
        case ProposalMade():
            return {
                "proposal_id": str(event.proposal_id),
                "actor_id": str(event.actor_id),
                "plan_id": str(event.plan_id),
                "parameters": dict(event.parameters),
                "occurred_at": event.occurred_at.isoformat(),
            }
        case ProposalTaken():
            return {
                "proposal_id": str(event.proposal_id),
                "execution_id": str(event.execution_id),
                "step_id": str(event.step_id),
                "occurred_at": event.occurred_at.isoformat(),
            }
        case _:
            assert_never(event)


def from_stored(stored: StoredEvent) -> ProposalEvent:
    """Rebuild an event from its stored row.

    `extra` carries `ValueError` because the constructors below raise it
    on malformed input: strings that are not UUIDs, and one that is not a
    timestamp. Without it those escape as themselves, naming the field
    rather than the event.
    """
    payload = stored.payload
    match stored.event_type:
        case "ProposalMade":
            return deserialize_or_raise(
                "ProposalMade",
                lambda: ProposalMade(
                    proposal_id=UUID(payload["proposal_id"]),
                    actor_id=UUID(payload["actor_id"]),
                    plan_id=UUID(payload["plan_id"]),
                    parameters=dict(payload["parameters"]),
                    occurred_at=datetime.fromisoformat(payload["occurred_at"]),
                ),
                extra=(ValueError,),
            )
        case "ProposalTaken":
            return deserialize_or_raise(
                "ProposalTaken",
                lambda: ProposalTaken(
                    proposal_id=UUID(payload["proposal_id"]),
                    execution_id=UUID(payload["execution_id"]),
                    step_id=UUID(payload["step_id"]),
                    occurred_at=datetime.fromisoformat(payload["occurred_at"]),
                ),
                extra=(ValueError,),
            )
        case unknown:
            msg = f"Unknown Proposal event_type: {unknown!r}"
            raise ValueError(msg)


__all__ = [
    "ProposalEvent",
    "ProposalMade",
    "ProposalTaken",
    "from_stored",
    "to_payload",
]
