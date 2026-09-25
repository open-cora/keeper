"""Authorize port: gate every command behind authz.authorize(principal, command, surface).

`principal_id` (not `actor_id`) names the invoker so that a BC owning an
actor-like aggregate can use its own id field without collision. Reusing
one name for both the target aggregate's id and the calling party's id
was a real bug vector at handler call sites where a command targets the
same kind of thing that issued it.

`surface_id: UUID` names the process-level arrival point (HTTP /
MCP stdio / MCP streamable-http) through which the request entered
The keeper. Every route and tool resolves a concrete one per request from
the constants in `keeper.infrastructure.request`; no aggregate models a
surface today, so those constants are a namespace rather than foreign
keys. Edge auth layers OAuth `aud` validation on top.

`surface_id` defaults to the nil `UUID(int=0)` sentinel for callers
with no request context, such as a unit test driving a handler
directly. A surface reaching `authorize` on that default is now a
failure rather than a possibility: every tool is pinned to
`get_mcp_surface_id` by `test_tools_resolve_the_caller_at_the_boundary.py`
and every route to `Depends(get_surface_id)` by
`test_routes_resolve_the_caller_from_a_dependency.py`. Neither rule
existed while there was one bounded context for it to range over, which
was the right call then and stopped being one at the second.

`AllowAllAuthorize` is the no-op stub used for dev/test and for the
bootstrap workflow: define the gating policy under it, then restart with
a real adapter wired against that policy. The production adapter is
`keeper.authority.PolicyAuthorize`, reached through the `build_authorize`
factory that `api/main.py` hands to `build_kernel`, so the composition
root never imports a bounded context.
"""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from keeper.shared.reserved_ids import NIL_SENTINEL_ID


@dataclass(frozen=True)
class Allow:
    """Authorization granted."""


@dataclass(frozen=True)
class Deny:
    """Authorization denied with a reason.

    `reason` is operator-facing: it reaches the caller as the body of a
    403, so it says what was refused without saying what would have been
    permitted.
    """

    reason: str


type AuthzResult = Allow | Deny


class Authorize(Protocol):
    """Authorization gate: called before every command.

    Named-method (not `__call__`) per Python typing-community guidance
    (PEP 544 + typing spec + mypy docs): `__call__` Protocols are for
    callback signatures `Callable[...]` can't express (variadic,
    overloaded, complex generic). A single-operation domain port uses
    a regular method, matching the keeper's other ports (`Clock.now`,
    `EventStore.load`, `TokenVerifier.verify`, …) and the broader
    authorization-library corpus (Spring Security 6's
    `AuthorizationManager.authorize`, Pundit's `authorize`, Cedar's
    `is_authorized`, Casbin's `enforce`).

    The seam: `Kernel.authz: Authorize` with call sites reading
    `await deps.authz.authorize(...)`: "use the authz port to
    authorize this command." A factory protocol such as
    `AuthorizeFactory` DOES use `__call__`, because it IS a construction
    function; this port is not.
    """

    async def authorize(
        self,
        principal_id: UUID,
        command_name: str,
        surface_id: UUID = NIL_SENTINEL_ID,
    ) -> AuthzResult: ...


class AllowAllAuthorize:
    """No-op stub: returns Allow for every call.

    Production wiring injects a real adapter via `build_kernel(authorize_factory=...)`;
    AllowAll remains for tests/dev and the documented bootstrap
    workflow (define the gating policy under AllowAll, then restart
    with a real authorize adapter wired against it).
    """

    async def authorize(
        self,
        principal_id: UUID,
        command_name: str,
        surface_id: UUID = NIL_SENTINEL_ID,
    ) -> AuthzResult:
        _ = (principal_id, command_name, surface_id)
        return Allow()
