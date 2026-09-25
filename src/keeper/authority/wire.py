"""Compose the Authority handlers from the process-wide dependencies.

`wire_authority(deps)` runs once during startup and the bundle it
returns is attached to the app. Routes and MCP tools both pull their
handler out of that bundle, which is what keeps the two surfaces calling
the same code rather than two copies of it.

Wrapping order, innermost first:

  1. bind          the bare handler
  2. idempotency   a replayed key returns the first answer instead of
                   authoring a second policy
  3. tracing       one span per call, whether or not the key hit cache

Defining a policy takes the middle layer because it mints a stream: a
retried definition without it produces two rulebooks, and a deployment
then authorizes against whichever id someone wrote down.

Granting and revoking go without it. A replayed one of either is
already refused by the domain, so the wrapper would buy a friendlier
status code rather than prevent a second write. Reading goes without it
because a retried read has nothing to replay.
"""

from dataclasses import dataclass
from uuid import UUID

from keeper.authority.features import (
    define_policy,
    get_policy,
    grant_permission,
    revoke_permission,
)
from keeper.infrastructure.kernel import Kernel
from keeper.infrastructure.observability import with_tracing
from keeper.infrastructure.slices.idempotency import with_idempotency

_BC = "authority"


@dataclass(frozen=True)
class AuthorityHandlers:
    """The bundle, one field per slice."""

    define_policy: define_policy.IdempotentHandler
    grant_permission: grant_permission.Handler
    revoke_permission: revoke_permission.Handler
    get_policy: get_policy.Handler


def wire_authority(deps: Kernel) -> AuthorityHandlers:
    """Build the Authority handlers."""
    return AuthorityHandlers(
        define_policy=with_tracing(
            with_idempotency(
                define_policy.bind(deps),
                deps.idempotency_store,
                command_name="DefinePolicy",
                serialize_result=str,
                deserialize_result=lambda raw: UUID(str(raw)),
                lock_stale_seconds=deps.settings.idempotency_lock_stale_seconds,
            ),
            command_name="DefinePolicy",
            bc=_BC,
        ),
        grant_permission=with_tracing(
            grant_permission.bind(deps),
            command_name="GrantPolicyPermission",
            bc=_BC,
        ),
        revoke_permission=with_tracing(
            revoke_permission.bind(deps),
            command_name="RevokePolicyPermission",
            bc=_BC,
        ),
        get_policy=with_tracing(
            get_policy.bind(deps),
            command_name="GetPolicy",
            bc=_BC,
        ),
    )


__all__ = ["AuthorityHandlers", "wire_authority"]
