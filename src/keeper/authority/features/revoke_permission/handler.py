"""Run the revoke: authorize, load, decide, append.

Update-style. The policy already exists, so the handler loads and folds
it first, and passes the version it read back as `expected_version`: two
operators revoking at once produce one append and one `ConcurrencyError`
rather than two appends that each believed they were first.

That version matters more here than it does for a grant. Two concurrent
revokes each fold a policy that still holds a governing permission, so
each passes the governance guard on its own, and without the version
check both would land and leave a policy nobody can change. The guard is
correct about the state it was given; the version is what makes the
state it was given still true at the moment of the write.

No idempotency wrapper. A replayed revoke is already refused by the
domain, so a retry key would buy a friendlier status code rather than
prevent a second write.
"""

from typing import Protocol
from uuid import UUID

from keeper.authority.aggregates.policy import (
    POLICY_STREAM_TYPE,
    load_policy_with_version,
    to_payload,
)
from keeper.authority.errors import UnauthorizedError
from keeper.authority.features.revoke_permission.command import RevokePolicyPermission
from keeper.authority.features.revoke_permission.decider import decide
from keeper.infrastructure.kernel import Kernel
from keeper.infrastructure.logging import get_logger
from keeper.infrastructure.ports import Deny
from keeper.infrastructure.slices.envelope import to_new_event
from keeper.shared.reserved_ids import NIL_SENTINEL_ID

_COMMAND_NAME = "RevokePolicyPermission"

_log = get_logger(__name__)


class Handler(Protocol):
    """The bare handler. No idempotent variant; see the module docstring."""

    async def __call__(
        self,
        command: RevokePolicyPermission,
        *,
        principal_id: UUID,
        correlation_id: UUID,
        causation_id: UUID | None = None,
        surface_id: UUID = NIL_SENTINEL_ID,
    ) -> None: ...


def bind(deps: Kernel) -> Handler:
    """Build the handler, closed over the process-wide dependencies."""

    async def handler(
        command: RevokePolicyPermission,
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
                "revoke_permission.denied",
                command_name=_COMMAND_NAME,
                policy_id=str(command.policy_id),
                principal_id=str(principal_id),
                correlation_id=str(correlation_id),
                reason=decision.reason,
            )
            raise UnauthorizedError(decision.reason)

        state, version = await load_policy_with_version(deps.event_store, command.policy_id)
        now = deps.clock.now()
        events = decide(state, command, now=now)

        await deps.event_store.append(
            POLICY_STREAM_TYPE,
            command.policy_id,
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
            "revoke_permission.success",
            command_name=_COMMAND_NAME,
            policy_id=str(command.policy_id),
            revoked_from=str(command.permission.principal_id),
            revoked_command=command.permission.command_name,
            principal_id=str(principal_id),
            correlation_id=str(correlation_id),
        )

    return handler


__all__ = ["Handler", "bind"]
