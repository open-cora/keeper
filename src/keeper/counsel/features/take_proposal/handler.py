"""Record the acquisition: authorize, load both, decide, append.

Update-style, so this command names a stream that already has a row. The
handler folds that history before deciding and passes the version it
read back as `expected_version`.

That version is the whole of the concurrency story. Two callers taking
the same proposal at once both fold the same state and both decide to
append at the same version; the store lets one through and raises
`ConcurrencyError` at the other, which surfaces as a 409. Without it the
second append would land a second run against a proposal that already
had one, which the decider exists to refuse.

Three loads and four refusals before the decision. The proposal is
loaded first because its version is needed either way, and the execution
is refused here, so a request naming neither a real proposal nor a real
execution is answered about the execution. All are 404 and such a caller
has two things to fix; picking the other order would just move which one
it hears about first.

The second and third refusals are what a step reference costs, and they
are the same ones `register_dataset` pays. A step is an entity inside the
Execution aggregate rather than a stream of its own, so nothing can load
one by itself: establishing that a step exists means loading the
execution around it, and the step is then in hand.

The third load is the procedure, and it is where this parts company with
`register_dataset`. That slice needs the step to exist and nothing more.
This one asks what the step was composed to do, and the answer is on the
procedure rather than copied onto the execution, so the reference on the
step is followed one hop further. Its two refusals cannot be reached
through the ordinary path: an execution cites the procedure it was
dispatched from and each of its steps cites a composed step of it, a
procedure has one event, and nothing edits one.

`ExecutionNotFoundError`, `ExecutionStepNotFoundError`,
`ProcedureNotFoundError` and `ProcedureStepNotFoundError` are Execution's
classes, raised from here and mapped to 404 by Execution's registration
rather than by anything on Counsel's routes.

No idempotency wrapper. A replayed take is already refused by the
domain, so the wrapper would be buying a nicer status code for a retry
rather than preventing a duplicate. See the wiring module, which says
which layers a slice gets and why.
"""

from typing import Protocol
from uuid import UUID

from keeper.counsel.aggregates.proposal import (
    PROPOSAL_STREAM_TYPE,
    load_proposal_with_version,
    to_payload,
)
from keeper.counsel.errors import UnauthorizedError
from keeper.counsel.features.take_proposal.command import TakeProposal
from keeper.counsel.features.take_proposal.context import TakeProposalContext
from keeper.counsel.features.take_proposal.decider import decide
from keeper.execution.aggregates.execution import (
    ExecutionNotFoundError,
    ExecutionStepNotFoundError,
    load_execution,
)
from keeper.execution.aggregates.procedure import (
    ProcedureNotFoundError,
    ProcedureStepNotFoundError,
    load_procedure,
)
from keeper.infrastructure.kernel import Kernel
from keeper.infrastructure.logging import get_logger
from keeper.infrastructure.ports import Deny
from keeper.infrastructure.slices.envelope import to_new_event
from keeper.shared.reserved_ids import NIL_SENTINEL_ID

_COMMAND_NAME = "TakeProposal"

_log = get_logger(__name__)


class Handler(Protocol):
    """The bare handler, before the wrapping the wire module applies."""

    async def __call__(
        self,
        command: TakeProposal,
        *,
        principal_id: UUID,
        correlation_id: UUID,
        causation_id: UUID | None = None,
        surface_id: UUID = NIL_SENTINEL_ID,
    ) -> None: ...


def bind(deps: Kernel) -> Handler:
    """Build the handler, closed over the process-wide dependencies."""

    async def handler(
        command: TakeProposal,
        *,
        principal_id: UUID,
        correlation_id: UUID,
        causation_id: UUID | None = None,
        surface_id: UUID = NIL_SENTINEL_ID,
    ) -> None:
        decision = await deps.authz.authorize(
            principal_id=principal_id,
            command_name=_COMMAND_NAME,
            surface_id=surface_id,
        )
        if isinstance(decision, Deny):
            _log.info(
                "take_proposal.denied",
                command_name=_COMMAND_NAME,
                proposal_id=str(command.proposal_id),
                execution_id=str(command.execution_id),
                step_id=str(command.step_id),
                principal_id=str(principal_id),
                correlation_id=str(correlation_id),
                reason=decision.reason,
            )
            raise UnauthorizedError(decision.reason)

        state, version = await load_proposal_with_version(deps.event_store, command.proposal_id)
        execution = await load_execution(deps.event_store, command.execution_id)
        if execution is None:
            raise ExecutionNotFoundError(command.execution_id)
        step = next((s for s in execution.steps if s.id == command.step_id), None)
        if step is None:
            raise ExecutionStepNotFoundError(command.execution_id, command.step_id)

        procedure = await load_procedure(deps.event_store, execution.procedure_id)
        if procedure is None:
            raise ProcedureNotFoundError(execution.procedure_id)
        composed = procedure.step(step.procedure_step_id)
        if composed is None:
            raise ProcedureStepNotFoundError(procedure.id, step.procedure_step_id)

        now = command.occurred_at if command.occurred_at is not None else deps.clock.now()
        events = decide(state, command, context=TakeProposalContext(composed=composed), now=now)

        await deps.event_store.append(
            PROPOSAL_STREAM_TYPE,
            command.proposal_id,
            version,
            [
                to_new_event(
                    event_type=type(event).__name__,
                    payload=to_payload(event),
                    occurred_at=event.occurred_at,
                    event_id=deps.id_generator.new_id(),
                    command_name=_COMMAND_NAME,
                    correlation_id=correlation_id,
                    causation_id=causation_id,
                    principal_id=principal_id,
                )
                for event in events
            ],
        )

        _log.info(
            "take_proposal.success",
            command_name=_COMMAND_NAME,
            proposal_id=str(command.proposal_id),
            execution_id=str(command.execution_id),
            step_id=str(command.step_id),
            principal_id=str(principal_id),
            correlation_id=str(correlation_id),
        )

    return handler


__all__ = ["Handler", "bind"]
