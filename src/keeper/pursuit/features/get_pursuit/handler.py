"""Read one pursuit: authorize, load, fold, answer.

Folded from the stream rather than read from a table. A pursuit's stream
is a handful of rows and this names one, so there is nothing a projection
would buy. Listing them is the question that would need one, and nothing
asks it yet.
"""

from typing import Protocol
from uuid import UUID

from keeper.infrastructure.kernel import Kernel
from keeper.infrastructure.logging import get_logger
from keeper.infrastructure.ports import Deny
from keeper.pursuit.aggregates.pursuit import Pursuit, PursuitNotFoundError, load_pursuit
from keeper.pursuit.features.get_pursuit.query import GetPursuit
from keeper.shared.reserved_ids import NIL_SENTINEL_ID
from keeper.shared.unauthorized import UnauthorizedError

_COMMAND_NAME = "GetPursuit"

_log = get_logger(__name__)


class Handler(Protocol):
    """The bare handler, before the wrapping the wire module applies."""

    async def __call__(
        self,
        query: GetPursuit,
        *,
        principal_id: UUID,
        correlation_id: UUID,
        causation_id: UUID | None = None,
        surface_id: UUID = NIL_SENTINEL_ID,
    ) -> Pursuit: ...


def bind(deps: Kernel) -> Handler:
    """Build the handler, closed over the process-wide dependencies."""

    async def handler(
        query: GetPursuit,
        *,
        principal_id: UUID,
        correlation_id: UUID,
        causation_id: UUID | None = None,
        surface_id: UUID = NIL_SENTINEL_ID,
    ) -> Pursuit:
        _ = causation_id
        decision = await deps.authz.authorize(
            principal_id=principal_id,
            command_name=_COMMAND_NAME,
            surface_id=surface_id,
        )
        if isinstance(decision, Deny):
            _log.info(
                "get_pursuit.denied",
                command_name=_COMMAND_NAME,
                pursuit_id=str(query.pursuit_id),
                principal_id=str(principal_id),
                correlation_id=str(correlation_id),
                reason=decision.reason,
            )
            raise UnauthorizedError(decision.reason)

        pursuit = await load_pursuit(deps.event_store, query.pursuit_id)
        if pursuit is None:
            raise PursuitNotFoundError(query.pursuit_id)
        return pursuit

    return handler


__all__ = ["Handler", "bind"]
