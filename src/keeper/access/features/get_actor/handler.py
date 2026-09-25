"""Answer the question: authorize, load, return.

No decider, no append, no clock. A read produces no events, so there is
nothing for a pure decision function to decide and nothing to make
reproducible on replay.

Authorization still happens. Reading who a system has a record of is a
capability like any other, and a slice that skipped the check because it
writes nothing would be the one place a caller could learn something
without being allowed to.

`ActorNotFoundError` rather than a `None` return. The aggregate's
`load_actor` returns None and leaves the meaning to its caller, which is
this handler: both surfaces want a refusal, and raising the same error
the writing slices raise gets it mapped in one place instead of two.
"""

from typing import Protocol
from uuid import UUID

from keeper.access.aggregates.actor import Actor, ActorNotFoundError, load_actor
from keeper.access.errors import UnauthorizedError
from keeper.access.features.get_actor.query import GetActor
from keeper.infrastructure.kernel import Kernel
from keeper.infrastructure.logging import get_logger
from keeper.infrastructure.ports import Deny
from keeper.shared.reserved_ids import NIL_SENTINEL_ID

_COMMAND_NAME = "GetActor"

_log = get_logger(__name__)


class Handler(Protocol):
    """The bare handler, before the wrapping the wire module applies."""

    async def __call__(
        self,
        query: GetActor,
        *,
        principal_id: UUID,
        correlation_id: UUID,
        causation_id: UUID | None = None,
        surface_id: UUID = NIL_SENTINEL_ID,
    ) -> Actor: ...


def bind(deps: Kernel) -> Handler:
    """Build the handler, closed over the process-wide dependencies."""

    async def handler(
        query: GetActor,
        *,
        principal_id: UUID,
        correlation_id: UUID,
        causation_id: UUID | None = None,
        surface_id: UUID = NIL_SENTINEL_ID,
    ) -> Actor:
        _ = causation_id
        decision = await deps.authz.authorize(
            principal_id=principal_id,
            command_name=_COMMAND_NAME,
            surface_id=surface_id,
        )
        if isinstance(decision, Deny):
            _log.info(
                "get_actor.denied",
                command_name=_COMMAND_NAME,
                actor_id=str(query.actor_id),
                principal_id=str(principal_id),
                correlation_id=str(correlation_id),
                reason=decision.reason,
            )
            raise UnauthorizedError(decision.reason)

        actor = await load_actor(deps.event_store, query.actor_id)
        if actor is None:
            raise ActorNotFoundError(query.actor_id)
        return actor

    return handler


__all__ = ["Handler", "bind"]
