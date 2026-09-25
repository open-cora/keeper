"""Answer the question: authorize, load, return.

No decider, no append, no clock. A read produces no events, so there is
nothing for a pure decision function to decide and nothing to make
reproducible on replay.

Authorization still happens, and it is worth more here than it is on
most reads. A rulebook says who may do what, which is a map of
everything the system will accept, so a caller who can read one learns
where to aim without being permitted anything by it.

`GetPolicy` is deliberately NOT a governing command. Losing the ability
to read a policy is uncomfortable and not unrecoverable: whoever may
grant can grant the read back, and until they do the policy can still be
changed blind. Only a power that cannot be restored belongs in the set
that every policy is forced to carry.

`PolicyNotFoundError` rather than a `None` return. The aggregate's
`load_policy` returns None and leaves the meaning to its caller, which
is this handler: both surfaces want a refusal, and raising the same
error the writing slices raise gets it mapped in one place instead of
two.
"""

from typing import Protocol
from uuid import UUID

from keeper.authority.aggregates.policy import Policy, PolicyNotFoundError, load_policy
from keeper.authority.errors import UnauthorizedError
from keeper.authority.features.get_policy.query import GetPolicy
from keeper.infrastructure.kernel import Kernel
from keeper.infrastructure.logging import get_logger
from keeper.infrastructure.ports import Deny
from keeper.shared.reserved_ids import NIL_SENTINEL_ID

_COMMAND_NAME = "GetPolicy"

_log = get_logger(__name__)


class Handler(Protocol):
    """The bare handler, before the wrapping the wire module applies."""

    async def __call__(
        self,
        query: GetPolicy,
        *,
        principal_id: UUID,
        correlation_id: UUID,
        causation_id: UUID | None = None,
        surface_id: UUID = NIL_SENTINEL_ID,
    ) -> Policy: ...


def bind(deps: Kernel) -> Handler:
    """Build the handler, closed over the process-wide dependencies."""

    async def handler(
        query: GetPolicy,
        *,
        principal_id: UUID,
        correlation_id: UUID,
        causation_id: UUID | None = None,
        surface_id: UUID = NIL_SENTINEL_ID,
    ) -> Policy:
        _ = causation_id
        decision = await deps.authz.authorize(
            principal_id=principal_id,
            command_name=_COMMAND_NAME,
            surface_id=surface_id,
        )
        if isinstance(decision, Deny):
            _log.info(
                "get_policy.denied",
                command_name=_COMMAND_NAME,
                policy_id=str(query.policy_id),
                principal_id=str(principal_id),
                correlation_id=str(correlation_id),
                reason=decision.reason,
            )
            raise UnauthorizedError(decision.reason)

        policy = await load_policy(deps.event_store, query.policy_id)
        if policy is None:
            raise PolicyNotFoundError(query.policy_id)
        return policy

    return handler


__all__ = ["Handler", "bind"]
