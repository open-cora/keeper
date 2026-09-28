"""Adopt the proposal: authorize, load, decide three times, append once.

The one slice in this tree that writes to more than one bounded
context's streams, and the first consumer of `EventStore.append_streams`,
whose own docstring has been waiting for one.

## Why it is here and not in Execution

Because the dependency cannot point the other way. Counsel may read
Execution and does; Execution knows nothing of Counsel and must not, so
a slice in Execution that loaded a proposal would be a cycle rather than
an edge. What lands here instead is the composition, and the price is
that this context's door onto Execution now reaches its feature layer.

## Why the composing is Execution's and only the write is ours

Composing a procedure and dispatching an execution are decisions about
Execution's aggregates, so Execution makes them, behind one function that
hands back the appends. This handler once assembled that itself out of
six of that context's names plus two stream types and two payload
renderers, which meant it knew not only what it wanted but how Execution
gets there. `keeper.execution.composing` holds that now, and the door it
left behind is six names narrower.

What does not move is the transaction. The appends come back undone, this
handler adds its own and commits all three, because the proposal being
adopted is this context's fact and Execution knows nothing of it.

## What one transaction buys

A crash between dispatching and recording the adoption would otherwise
leave a beamline running work that the proposal does not know about, so
a second caller adopting the same proposal would run it twice. Three
streams in one append removes the window rather than narrowing it: the
procedure, the execution and the adoption all exist, or none does and
nothing was dispatched.

The proposal's `expected_version` is the other half. Two callers
adopting one proposal both fold the same state and both append at the
same version, and the store lets exactly one through.
"""

from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from keeper.counsel.aggregates.proposal import (
    PROPOSAL_STREAM_TYPE,
    ProposalNotFoundError,
    load_proposal_with_version,
    to_payload,
)
from keeper.counsel.features.adopt_proposal.command import AdoptProposal
from keeper.counsel.features.adopt_proposal.decider import decide
from keeper.execution.aggregates.plan import PlanNotFoundError, load_plan
from keeper.execution.composing import compose_one_run
from keeper.infrastructure.kernel import Kernel
from keeper.infrastructure.logging import get_logger
from keeper.infrastructure.ports import Deny
from keeper.infrastructure.ports.event_store import NewEvent, StreamAppend
from keeper.infrastructure.slices.envelope import to_new_event
from keeper.shared.reserved_ids import NIL_SENTINEL_ID
from keeper.shared.unauthorized import UnauthorizedError

_COMMAND_NAME = "AdoptProposal"

_log = get_logger(__name__)


class Handler(Protocol):
    """The bare handler, before the wrapping the wire module applies."""

    async def __call__(
        self,
        command: AdoptProposal,
        *,
        principal_id: UUID,
        correlation_id: UUID,
        causation_id: UUID | None = None,
        surface_id: UUID = NIL_SENTINEL_ID,
    ) -> UUID: ...


class IdempotentHandler(Protocol):
    """The same handler once the idempotency wrapper is around it.

    One extra keyword. None means behave exactly like the bare handler,
    which is what every caller without a retry key gets.
    """

    async def __call__(
        self,
        command: AdoptProposal,
        *,
        principal_id: UUID,
        correlation_id: UUID,
        causation_id: UUID | None = None,
        surface_id: UUID = NIL_SENTINEL_ID,
        idempotency_key: str | None = None,
    ) -> UUID: ...


def bind(deps: Kernel) -> Handler:
    """Build the handler, closed over the process-wide dependencies."""

    async def handler(
        command: AdoptProposal,
        *,
        principal_id: UUID,
        correlation_id: UUID,
        causation_id: UUID | None = None,
        surface_id: UUID = NIL_SENTINEL_ID,
    ) -> UUID:
        decision = await deps.authz.authorize(
            principal_id=principal_id,
            command_name=_COMMAND_NAME,
            surface_id=surface_id,
        )
        if isinstance(decision, Deny):
            _log.info(
                "adopt_proposal.denied",
                command_name=_COMMAND_NAME,
                proposal_id=str(command.proposal_id),
                principal_id=str(principal_id),
                correlation_id=str(correlation_id),
                reason=decision.reason,
            )
            raise UnauthorizedError(decision.reason)

        proposal, version = await load_proposal_with_version(deps.event_store, command.proposal_id)
        if proposal is None:
            raise ProposalNotFoundError(command.proposal_id)
        plan = await load_plan(deps.event_store, proposal.plan_id)
        if plan is None:
            raise PlanNotFoundError(proposal.plan_id)

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

        run = compose_one_run(
            plan=plan,
            parameters=proposal.parameters,
            beamline=command.beamline,
            scopes=command.scopes,
            now=now,
            new_id=deps.id_generator.new_id,
            envelope=envelope,
        )
        adoption_events = decide(
            proposal,
            command,
            execution_id=run.execution_id,
            step_id=run.step_id,
            now=now,
        )

        await deps.event_store.append_streams(
            [
                *run.appends,
                StreamAppend(
                    stream_type=PROPOSAL_STREAM_TYPE,
                    stream_id=command.proposal_id,
                    expected_version=version,
                    events=[
                        envelope(
                            type(event).__name__,
                            to_payload(event),
                            event.occurred_at,
                        )
                        for event in adoption_events
                    ],
                ),
            ]
        )

        _log.info(
            "adopt_proposal.success",
            command_name=_COMMAND_NAME,
            proposal_id=str(command.proposal_id),
            execution_id=str(run.execution_id),
            beamline=command.beamline,
            principal_id=str(principal_id),
            correlation_id=str(correlation_id),
        )
        return run.execution_id

    return handler


__all__ = ["Handler", "IdempotentHandler", "bind"]
