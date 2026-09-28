"""Open the round: authorize, load two aggregates, decide twice, append once.

The second slice in this tree that writes to more than one bounded
context's streams, after Counsel's adoption, and it is the smaller of the
two: two streams rather than three, and one of them a genesis.

## Why it is here and not in Counsel

Because the dependency cannot point the other way. Pursuit may read
Counsel and does; Counsel knows nothing of Pursuit and must not, so a
slice in Counsel that loaded a pursuit would be a cycle rather than an
edge. What lands here instead is the composition, and the price is that
this context's door reaches Counsel's feature layer.

## Why Counsel's decider makes the inquiry

Putting a question is a decision about Counsel's aggregate, so Counsel's
own decider makes it. It is a pure function over values, which is what
lets this handler call it without going through its handler, and going
through its handler is exactly what would break the property this slice
exists for: it would append on its own and the two writes would stop being
one.

So the decision stays where it is modelled and only the append moves.

## What one transaction buys

A crash between the two would leave a question nobody's pursuit is waiting
on, or a round citing a question that does not exist. The second is the
one that matters: the round is what the budget counts and what refuses a
repeat, so a round without its inquiry would spend the budget and produce
nothing, and the caller retrying would be refused by the round its own
failure left behind.

Two streams in one append removes the window rather than narrowing it. The
pursuit's `expected_version` is the other half, and it is what makes the
caller safe to duplicate: two drivers open the same round, both append at
the version they folded, and the store lets exactly one through.
"""

from typing import Any, Protocol
from uuid import UUID

from keeper.counsel.aggregates.inquiry import INQUIRY_STREAM_TYPE
from keeper.counsel.aggregates.inquiry import to_payload as inquiry_payload
from keeper.counsel.features.make_inquiry import MakeInquiry, MakeInquiryContext
from keeper.counsel.features.make_inquiry import decide as decide_inquiry
from keeper.execution.aggregates.execution import ExecutionNotFoundError, load_execution
from keeper.infrastructure.kernel import Kernel
from keeper.infrastructure.logging import get_logger
from keeper.infrastructure.ports import Deny
from keeper.infrastructure.ports.event_store import NewEvent, StreamAppend
from keeper.infrastructure.slices.envelope import to_new_event
from keeper.pursuit.aggregates.pursuit import (
    PURSUIT_STREAM_TYPE,
    PursuitNotFoundError,
    load_pursuit_with_version,
    to_payload,
)
from keeper.pursuit.features.open_pursuit_round.command import OpenPursuitRound
from keeper.pursuit.features.open_pursuit_round.decider import decide
from keeper.shared.reserved_ids import NIL_SENTINEL_ID
from keeper.shared.unauthorized import UnauthorizedError

_COMMAND_NAME = "OpenPursuitRound"

_log = get_logger(__name__)


class Handler(Protocol):
    """The bare handler, before the wrapping the wire module applies."""

    async def __call__(
        self,
        command: OpenPursuitRound,
        *,
        principal_id: UUID,
        correlation_id: UUID,
        causation_id: UUID | None = None,
        surface_id: UUID = NIL_SENTINEL_ID,
    ) -> UUID: ...


class IdempotentHandler(Protocol):
    """The same handler once the idempotency wrapper is around it.

    One extra keyword. None means behave exactly like the bare handler,
    which is what every caller without a retry key gets, and here that
    caller is already protected: a second round about one execution is
    refused by the pursuit itself.
    """

    async def __call__(
        self,
        command: OpenPursuitRound,
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
        command: OpenPursuitRound,
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
                "open_pursuit_round.denied",
                command_name=_COMMAND_NAME,
                pursuit_id=str(command.pursuit_id),
                execution_id=str(command.execution_id),
                principal_id=str(principal_id),
                correlation_id=str(correlation_id),
                reason=decision.reason,
            )
            raise UnauthorizedError(decision.reason)

        pursuit, version = await load_pursuit_with_version(deps.event_store, command.pursuit_id)
        if pursuit is None:
            raise PursuitNotFoundError(command.pursuit_id)
        execution = await load_execution(deps.event_store, command.execution_id)
        if execution is None:
            raise ExecutionNotFoundError(command.execution_id)

        now = deps.clock.now()
        inquiry_id = deps.id_generator.new_id()

        round_events = decide(pursuit, command, inquiry_id=inquiry_id, now=now)
        inquiry_events = decide_inquiry(
            None,
            MakeInquiry(execution_id=command.execution_id, objective=pursuit.goal.value),
            context=MakeInquiryContext(execution=execution),
            actor_id=principal_id,
            now=now,
            new_id=inquiry_id,
        )

        def envelope(event_type: str, payload: dict[str, Any], occurred_at: Any) -> NewEvent:
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
                    stream_type=INQUIRY_STREAM_TYPE,
                    stream_id=inquiry_id,
                    expected_version=0,
                    events=[
                        envelope(type(event).__name__, inquiry_payload(event), event.occurred_at)
                        for event in inquiry_events
                    ],
                ),
                StreamAppend(
                    stream_type=PURSUIT_STREAM_TYPE,
                    stream_id=command.pursuit_id,
                    expected_version=version,
                    events=[
                        envelope(type(event).__name__, to_payload(event), event.occurred_at)
                        for event in round_events
                    ],
                ),
            ]
        )

        _log.info(
            "open_pursuit_round.success",
            command_name=_COMMAND_NAME,
            pursuit_id=str(command.pursuit_id),
            round_index=round_events[0].round_index,
            execution_id=str(command.execution_id),
            inquiry_id=str(inquiry_id),
            principal_id=str(principal_id),
            correlation_id=str(correlation_id),
        )
        return inquiry_id

    return handler


__all__ = ["Handler", "IdempotentHandler", "bind"]
