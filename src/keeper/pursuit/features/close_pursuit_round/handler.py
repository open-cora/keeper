"""Close the round: read the answer, act on it, append once.

The widest write in this tree. Four streams across three bounded contexts
when the answer proposes something, one when it does not, and the
difference is decided from a record rather than from anything the caller
said.

## The four outcomes, and why one command

A thinker concludes one of four things and the inquiry already holds
which. So this is not four requests: it is one request to read an answer
and apply it, and a caller that could name the outcome would be able to
make a pursuit act on an answer nobody gave.

    Propose   the proposal is adopted at the pursuit's beamline, over the
              pursuit's scopes, and the round advances. Four streams.
    Stop      the objective is met, and the pursuit stops. One stream.
    Abstain   nothing to go on, and the pursuit holds. One stream.
    Refer     a person should look, and the pursuit holds. One stream.

The two that hold are reversible and the one that stops is not, which is
the only structural difference between them.

## Why the beamline and the scopes come from here

They are the two facts a proposal underdetermines and the two that must
never be inferred. A person stated them once when the pursuit was started,
and this is where that statement is applied. Nothing in this handler could
work them out and nothing tries: they are read off the pursuit, and a
caller has no way to supply its own.

That is the whole reason a pursuit exists. Adoption outside one asks a
caller for both every time, because outside one there is nobody who has
said them.

## Why this composes rather than calling adoption's handler

Counsel's adopting slice would append on its own, and the four writes
would stop being one. So its decider is called for the fact it owns, the
proposal being adopted, and `keeper.execution.composing` is called for the
run, and this handler commits all of it with its own round beside them.

The alternative would be to let the two happen apart and accept the
window. What is in that window is a beamline running work against a budget
that has not been debited, and a round that can be closed a second time
because the first close never landed.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from keeper.counsel.aggregates.inquiry import InquiryConclusion, InquiryNotFoundError, load_inquiry
from keeper.counsel.aggregates.proposal import (
    PROPOSAL_STREAM_TYPE,
    ProposalNotFoundError,
    load_proposal_with_version,
)
from keeper.counsel.aggregates.proposal import to_payload as proposal_payload
from keeper.counsel.features.adopt_proposal import AdoptProposal
from keeper.counsel.features.adopt_proposal import decide as decide_adoption
from keeper.execution.aggregates.plan import PlanNotFoundError, load_plan
from keeper.execution.composing import compose_one_run
from keeper.infrastructure.kernel import Kernel
from keeper.infrastructure.logging import get_logger
from keeper.infrastructure.ports import Deny
from keeper.infrastructure.ports.event_store import NewEvent, StreamAppend
from keeper.infrastructure.slices.envelope import to_new_event
from keeper.pursuit.aggregates.pursuit import (
    PURSUIT_STREAM_TYPE,
    Pursuit,
    PursuitNotFoundError,
    PursuitRoundCannotBeClosedError,
    RoundOutcome,
    load_pursuit_with_version,
    to_payload,
)
from keeper.pursuit.features.close_pursuit_round.command import ClosePursuitRound
from keeper.pursuit.features.close_pursuit_round.decider import decide
from keeper.shared.reserved_ids import NIL_SENTINEL_ID
from keeper.shared.unauthorized import UnauthorizedError

_COMMAND_NAME = "ClosePursuitRound"

_log = get_logger(__name__)

ANSWERS_TO: dict[InquiryConclusion, RoundOutcome] = {
    InquiryConclusion.PROPOSE: RoundOutcome.ADVANCED,
    InquiryConclusion.STOP: RoundOutcome.COMPLETED,
    InquiryConclusion.ABSTAIN: RoundOutcome.STALLED,
    InquiryConclusion.REFER: RoundOutcome.REFERRED,
}
"""Which of this context's outcomes each of the thinker's conclusions means.

Public, and a mapping rather than four branches, because it is the place
the two vocabularies meet and a reader should be able to see the whole
translation at once. Complete by construction: a conclusion added to the
four would fail the lookup below rather than falling through to a default,
which is the loud direction to fail in when the new conclusion is the one
that says to stop.

The two words differ on purpose. A conclusion is what a thinker reached
about an execution. An outcome is what became of a round. They coincide
today and are not the same kind of fact, so a pursuit citing the inquiry
and naming its own outcome says both without either standing in for the
other.
"""


@dataclass(frozen=True, slots=True)
class ClosedRound:
    """What closing a round came to, for whoever asked for it.

    The outcome is the part a caller branches on, and the execution is set
    only when there is one. A driver reads the first to decide whether to
    keep going and the second to know what to watch.
    """

    outcome: RoundOutcome
    dispatched_id: UUID | None


class Handler(Protocol):
    """The bare handler, before the wrapping the wire module applies."""

    async def __call__(
        self,
        command: ClosePursuitRound,
        *,
        principal_id: UUID,
        correlation_id: UUID,
        causation_id: UUID | None = None,
        surface_id: UUID = NIL_SENTINEL_ID,
    ) -> ClosedRound: ...


def bind(deps: Kernel) -> Handler:
    """Build the handler, closed over the process-wide dependencies."""

    async def handler(
        command: ClosePursuitRound,
        *,
        principal_id: UUID,
        correlation_id: UUID,
        causation_id: UUID | None = None,
        surface_id: UUID = NIL_SENTINEL_ID,
    ) -> ClosedRound:
        decision = await deps.authz.authorize(
            principal_id=principal_id,
            command_name=_COMMAND_NAME,
            surface_id=surface_id,
        )
        if isinstance(decision, Deny):
            _log.info(
                "close_pursuit_round.denied",
                command_name=_COMMAND_NAME,
                pursuit_id=str(command.pursuit_id),
                round_index=command.round_index,
                principal_id=str(principal_id),
                correlation_id=str(correlation_id),
                reason=decision.reason,
            )
            raise UnauthorizedError(decision.reason)

        pursuit, version = await load_pursuit_with_version(deps.event_store, command.pursuit_id)
        if pursuit is None:
            raise PursuitNotFoundError(command.pursuit_id)

        outcome = await _what_the_thinker_said(deps, pursuit, command)
        now = deps.clock.now()

        def envelope(event_type: str, payload: dict[str, Any], occurred_at: datetime) -> NewEvent:
            return to_new_event(
                event_type=event_type,
                payload=payload,
                occurred_at=occurred_at,
                event_id=deps.id_generator.new_id(),
                command_name=_COMMAND_NAME,
                correlation_id=correlation_id,
                causation_id=causation_id,
                principal_id=principal_id,
            )

        alongside: list[StreamAppend] = []
        proposal_id: UUID | None = None
        dispatched_id: UUID | None = None

        if outcome is RoundOutcome.ADVANCED:
            proposal_id, alongside, dispatched_id = await _the_work_it_becomes(
                deps, pursuit, command, now=now, envelope=envelope
            )

        closing = decide(
            pursuit,
            command,
            outcome=outcome,
            proposal_id=proposal_id,
            dispatched_id=dispatched_id,
            now=now,
        )

        await deps.event_store.append_streams(
            [
                *alongside,
                StreamAppend(
                    stream_type=PURSUIT_STREAM_TYPE,
                    stream_id=command.pursuit_id,
                    expected_version=version,
                    events=[
                        envelope(type(event).__name__, to_payload(event), event.occurred_at)
                        for event in closing
                    ],
                ),
            ]
        )

        _log.info(
            "close_pursuit_round.success",
            command_name=_COMMAND_NAME,
            pursuit_id=str(command.pursuit_id),
            round_index=command.round_index,
            outcome=outcome.value,
            dispatched_id=None if dispatched_id is None else str(dispatched_id),
            principal_id=str(principal_id),
            correlation_id=str(correlation_id),
        )
        return ClosedRound(outcome=outcome, dispatched_id=dispatched_id)

    async def _what_the_thinker_said(
        deps: Kernel, pursuit: Pursuit, command: ClosePursuitRound
    ) -> RoundOutcome:
        """Read the round's inquiry and translate its conclusion.

        The round is looked up here as well as in the decider, because the
        inquiry cannot be loaded without it. The decider checks it again
        rather than trusting this, since a decision that assumed its caller
        had already validated would be a decision that cannot be tested on
        its own.
        """
        turn = pursuit.round_at(command.round_index)
        if turn is None:
            raise PursuitRoundCannotBeClosedError(
                command.pursuit_id, command.round_index, "there is no such round"
            )
        inquiry = await load_inquiry(deps.event_store, turn.inquiry_id)
        if inquiry is None:
            raise InquiryNotFoundError(turn.inquiry_id)
        if inquiry.conclusion is None:
            raise PursuitRoundCannotBeClosedError(
                command.pursuit_id,
                command.round_index,
                f"its inquiry is {inquiry.status} and carries no answer yet",
            )
        return ANSWERS_TO[inquiry.conclusion]

    async def _the_work_it_becomes(
        deps: Kernel,
        pursuit: Pursuit,
        command: ClosePursuitRound,
        *,
        now: datetime,
        envelope: Any,
    ) -> tuple[UUID, list[StreamAppend], UUID]:
        """Adopt what was proposed, and compose the run it becomes.

        Only reached on the advancing outcome. The proposal is the one the
        inquiry named when it was answered, so nothing here chooses it.
        """
        turn = pursuit.round_at(command.round_index)
        inquiry = None if turn is None else await load_inquiry(deps.event_store, turn.inquiry_id)
        if inquiry is None or inquiry.proposal_id is None:
            raise PursuitRoundCannotBeClosedError(
                command.pursuit_id,
                command.round_index,
                "its inquiry proposed something and named no proposal",
            )

        proposal, proposal_version = await load_proposal_with_version(
            deps.event_store, inquiry.proposal_id
        )
        if proposal is None:
            raise ProposalNotFoundError(inquiry.proposal_id)
        plan = await load_plan(deps.event_store, proposal.plan_id)
        if plan is None:
            raise PlanNotFoundError(proposal.plan_id)

        run = compose_one_run(
            plan=plan,
            parameters=proposal.parameters,
            beamline=pursuit.beamline.value,
            scopes=pursuit.scopes,
            now=now,
            new_id=deps.id_generator.new_id,
            envelope=envelope,
        )
        adoption = decide_adoption(
            proposal,
            AdoptProposal(
                proposal_id=inquiry.proposal_id,
                beamline=pursuit.beamline.value,
                scopes=pursuit.scopes,
            ),
            execution_id=run.execution_id,
            step_id=run.step_id,
            now=now,
        )
        appends = [
            *run.appends,
            StreamAppend(
                stream_type=PROPOSAL_STREAM_TYPE,
                stream_id=inquiry.proposal_id,
                expected_version=proposal_version,
                events=[
                    envelope(type(event).__name__, proposal_payload(event), event.occurred_at)
                    for event in adoption
                ],
            ),
        ]
        return inquiry.proposal_id, appends, run.execution_id

    return handler


__all__ = ["ANSWERS_TO", "ClosedRound", "Handler", "bind"]
