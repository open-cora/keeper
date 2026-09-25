"""Run the registration: authorize, check the step, decide, append.

Create-style on its own stream, so there is no load-and-fold of a dataset
and `state=None` goes straight to the decider.

The execution is loaded and then only tested: that it exists, and that it
holds the step this dataset names. The handler fetches the sibling,
refuses a missing one itself, and passes nothing across to the decision.
`define_procedure` builds a context dataclass because its decider reads
the schemas of the plans it cites; this one has nothing to read, so there
is no context to build.

Two checks rather than one, and the second is what a step reference costs.
A step is an entity inside the Execution aggregate rather than a stream of
its own, so nothing can load one by itself: establishing that a step
exists means loading the execution around it. That is the price of
pointing at the acquisition instead of the traversal, and it is worth
paying: data belongs to one acquisition, and a reference to the whole
execution would lose which.

`ExecutionNotFoundError` and `ExecutionStepNotFoundError` are Execution's
classes, raised from here. Neither is re-registered on Custody's routes:
FastAPI's exception handlers are app-scoped and Execution already maps
both to 404, which is the rule in docs/reference/patterns.md for a
cross-BC domain error.

The execution is read and not touched, so one store is written, there is
no ordering to get right, and no window in which a crash leaves two
streams disagreeing. The read can be stale by the time the append lands,
which is accepted for the usual reason: what this check is for is
catching a caller who named the wrong step, not racing one being
dispatched.
"""

from typing import Protocol
from uuid import UUID

from keeper.custody.aggregates.dataset import DATASET_STREAM_TYPE, to_payload
from keeper.custody.errors import UnauthorizedError
from keeper.custody.features.register_dataset.command import RegisterDataset
from keeper.custody.features.register_dataset.decider import decide
from keeper.execution.aggregates.execution import (
    ExecutionNotFoundError,
    ExecutionStepNotFoundError,
    load_execution,
)
from keeper.infrastructure.kernel import Kernel
from keeper.infrastructure.logging import get_logger
from keeper.infrastructure.ports import Deny
from keeper.infrastructure.slices.envelope import to_new_event
from keeper.shared.reserved_ids import NIL_SENTINEL_ID

_COMMAND_NAME = "RegisterDataset"

_log = get_logger(__name__)


class Handler(Protocol):
    """The bare handler, before the wrapping the wire module applies."""

    async def __call__(
        self,
        command: RegisterDataset,
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
        command: RegisterDataset,
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
        command: RegisterDataset,
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
                "register_dataset.denied",
                command_name=_COMMAND_NAME,
                execution_id=str(command.execution_id),
                step_id=str(command.step_id),
                principal_id=str(principal_id),
                correlation_id=str(correlation_id),
                reason=decision.reason,
            )
            raise UnauthorizedError(decision.reason)

        execution = await load_execution(deps.event_store, command.execution_id)
        if execution is None:
            raise ExecutionNotFoundError(command.execution_id)
        if not any(step.id == command.step_id for step in execution.steps):
            raise ExecutionStepNotFoundError(command.execution_id, command.step_id)

        new_id = deps.id_generator.new_id()
        now = command.occurred_at if command.occurred_at is not None else deps.clock.now()
        events = decide(None, command, now=now, new_id=new_id)

        await deps.event_store.append(
            DATASET_STREAM_TYPE,
            new_id,
            0,
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
            "register_dataset.success",
            command_name=_COMMAND_NAME,
            dataset_id=str(new_id),
            execution_id=str(command.execution_id),
            step_id=str(command.step_id),
            external_ref_scheme=command.external_ref.scheme,
            principal_id=str(principal_id),
            correlation_id=str(correlation_id),
        )
        return new_id

    return handler


__all__ = ["Handler", "IdempotentHandler", "bind"]
