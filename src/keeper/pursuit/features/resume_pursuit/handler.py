"""Resume the pursuit: authorize, load, decide, append at the version folded.

The mirror of withdrawing, and the same three lines of reasoning apply to
it, so what is worth saying here is the difference. Withdrawing is the end
of an authorization and resuming is the middle of one, so a pursuit may be
held and resumed as many times as a thinker runs out of ideas and somebody
gives it more to go on. Each is its own row and none overwrites the last.

The version is what keeps two people resuming one pursuit from writing two
accounts of it coming back. Both fold the same held state, both append at
the same version, and the store lets one through.
"""

from typing import Protocol
from uuid import UUID

from keeper.infrastructure.kernel import Kernel
from keeper.infrastructure.logging import get_logger
from keeper.infrastructure.ports import Deny
from keeper.infrastructure.slices.envelope import to_new_event
from keeper.pursuit.aggregates.pursuit import (
    PURSUIT_STREAM_TYPE,
    PursuitNotFoundError,
    load_pursuit_with_version,
    to_payload,
)
from keeper.pursuit.features.resume_pursuit.command import ResumePursuit
from keeper.pursuit.features.resume_pursuit.decider import decide
from keeper.shared.reserved_ids import NIL_SENTINEL_ID
from keeper.shared.unauthorized import UnauthorizedError

_COMMAND_NAME = "ResumePursuit"

_log = get_logger(__name__)


class Handler(Protocol):
    """The bare handler, before the wrapping the wire module applies."""

    async def __call__(
        self,
        command: ResumePursuit,
        *,
        principal_id: UUID,
        correlation_id: UUID,
        causation_id: UUID | None = None,
        surface_id: UUID = NIL_SENTINEL_ID,
    ) -> None: ...


def bind(deps: Kernel) -> Handler:
    """Build the handler, closed over the process-wide dependencies."""

    async def handler(
        command: ResumePursuit,
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
                "resume_pursuit.denied",
                command_name=_COMMAND_NAME,
                pursuit_id=str(command.pursuit_id),
                principal_id=str(principal_id),
                correlation_id=str(correlation_id),
                reason=decision.reason,
            )
            raise UnauthorizedError(decision.reason)

        pursuit, version = await load_pursuit_with_version(deps.event_store, command.pursuit_id)
        if pursuit is None:
            raise PursuitNotFoundError(command.pursuit_id)

        events = decide(pursuit, command, actor_id=principal_id, now=deps.clock.now())

        await deps.event_store.append(
            PURSUIT_STREAM_TYPE,
            command.pursuit_id,
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
            "resume_pursuit.success",
            command_name=_COMMAND_NAME,
            pursuit_id=str(command.pursuit_id),
            started_by=str(pursuit.actor_id),
            held_for=None if pursuit.held_for is None else pursuit.held_for.value,
            principal_id=str(principal_id),
            correlation_id=str(correlation_id),
        )

    return handler


__all__ = ["Handler", "bind"]
