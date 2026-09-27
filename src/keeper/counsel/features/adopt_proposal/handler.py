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

## Why the deciders are Execution's and only the write is ours

Composing a procedure and dispatching an execution are decisions about
Execution's aggregates, so Execution's own deciders make them. They are
pure functions over values, which is what lets this handler call them
without going through their handlers, and going through their handlers
is exactly what would break the property this slice exists for: each
would append on its own and the three writes would stop being one.

So the decisions stay where they are modelled and only the append moves.

## Why the procedure is folded before it is stored

`dispatch_execution.decide` takes a `Procedure` as context, and the one
this dispatches was decided a few lines earlier and is not in any store
yet. Folding the event it produced is how a procedure that does not
exist becomes a value that does. The evolver is pure and total, so the
state this builds is byte for byte the state a later reader will fold
out of the same event.

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
from keeper.execution.aggregates.execution import EXECUTION_STREAM_TYPE
from keeper.execution.aggregates.execution import to_payload as execution_payload
from keeper.execution.aggregates.plan import PlanNotFoundError, load_plan
from keeper.execution.aggregates.procedure import (
    PROCEDURE_STREAM_TYPE,
    AcquireStep,
)
from keeper.execution.aggregates.procedure import (
    fold as fold_procedure,
)
from keeper.execution.aggregates.procedure import to_payload as procedure_payload
from keeper.execution.features.define_procedure import (
    DefineProcedure,
    DefineProcedureContext,
)
from keeper.execution.features.define_procedure import decide as decide_procedure
from keeper.execution.features.dispatch_execution import (
    DispatchExecution,
    DispatchExecutionContext,
)
from keeper.execution.features.dispatch_execution import decide as decide_execution
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
        procedure_id = deps.id_generator.new_id()
        composed_step_id = deps.id_generator.new_id()
        execution_id = deps.id_generator.new_id()
        dispatched_step_id = deps.id_generator.new_id()

        procedure_events = decide_procedure(
            None,
            DefineProcedure(
                name=plan.name.value,
                beamline=command.beamline,
                steps=(
                    AcquireStep(
                        plan_id=proposal.plan_id,
                        parameters=dict(proposal.parameters),
                        scopes=tuple(command.scopes),
                    ),
                ),
            ),
            context=DefineProcedureContext(plans={proposal.plan_id: plan}),
            now=now,
            new_id=procedure_id,
            step_ids=[composed_step_id],
        )
        composed = fold_procedure(procedure_events)
        if composed is None:
            msg = "defining a procedure produced no events, which its decider cannot do"
            raise RuntimeError(msg)

        execution_events = decide_execution(
            None,
            DispatchExecution(procedure_id=procedure_id),
            context=DispatchExecutionContext(procedure=composed),
            now=now,
            new_id=execution_id,
            step_ids=[dispatched_step_id],
        )
        adoption_events = decide(
            proposal,
            command,
            execution_id=execution_id,
            step_id=dispatched_step_id,
            now=now,
        )

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

        await deps.event_store.append_streams(
            [
                StreamAppend(
                    stream_type=PROCEDURE_STREAM_TYPE,
                    stream_id=procedure_id,
                    expected_version=0,
                    events=[
                        envelope(
                            type(event).__name__,
                            procedure_payload(event),
                            event.occurred_at,
                        )
                        for event in procedure_events
                    ],
                ),
                StreamAppend(
                    stream_type=EXECUTION_STREAM_TYPE,
                    stream_id=execution_id,
                    expected_version=0,
                    events=[
                        envelope(
                            type(event).__name__,
                            execution_payload(event),
                            event.occurred_at,
                        )
                        for event in execution_events
                    ],
                ),
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
            procedure_id=str(procedure_id),
            execution_id=str(execution_id),
            beamline=command.beamline,
            principal_id=str(principal_id),
            correlation_id=str(correlation_id),
        )
        return execution_id

    return handler


__all__ = ["Handler", "IdempotentHandler", "bind"]
