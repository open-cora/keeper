"""Authorize a command by asking the configured policy, and Access.

The real implementation of the `Authorize` port. Two conditions, both
required:

    permitted   the configured policy holds this exact
                (principal, command) pair
    standing    Access has a registered actor under that principal id,
                and it is active

Deny-by-default on each. A pair the policy does not hold is refused, so
the rulebook says what may happen rather than what may not, and a
principal Access does not recognise is refused whatever the rulebook
says.

## Why standing is checked here and not at the front door

Authentication never consults the Actor aggregate. It establishes WHO is
calling, from a token or a proxy-set header, and an actor being switched
off is not a fact about that. So without this check, deactivating an
actor takes nothing away: their grants keep working and the only way to
stop them is to revoke every permission they hold.

## The direction, which matters more than the check

Authority READS Access and never writes to it. Deactivating an actor
leaves every permission they hold sitting in the policy, inert;
reactivating makes them effective again with nothing re-granted. The
alternative, cascading a deactivation into revocations, would make
Access's gate quietly rewrite Authority's rulebook, and turn a
reversible switch into an act nobody can undo without knowing what was
there before.

## The cost, and the trap

Two folds per authorized request instead of one. Both streams are a
handful of rows.

The trap is worse than the cost and is the reason this is written down
twice, here and in docs/reference/runtime.md: a principal granted
permissions but never registered as an actor is refused. That is correct
and it is also how a deployment locks itself out, because the bootstrap
now has two steps in one order. Register the administrator in Access
FIRST, then author the policy naming them, then point AUTHZ_POLICY_ID at
it and restart.

## The order of the two checks

Policy first. A caller the rulebook does not name is refused without
Access being read at all, which keeps the denial path at one fold, and
it means "no actor" and "not active" only ever reach somebody the policy
does name. A caller who was granted nothing learns nothing about whether
this system has a record of them.

## What switching to this adapter costs

The system principal is refused everything. It cannot hold a permission,
because both writing paths refuse to grant it one, so the membership
test below simply never matches it. No branch does that; it falls out of
the model, and it is the whole point: under `AllowAllAuthorize` an
unauthenticated request runs as the system principal and is permitted
everything, and under this adapter it is permitted nothing.

That makes the cutover one-way through the API. A deployment authors its
first policy under `AllowAllAuthorize`, sets `AUTHZ_POLICY_ID`, and
restarts. It cannot author one afterwards, because defining a policy is
itself a command this adapter would deny.

## A configured policy that does not exist

Denied, every command, with the reason naming no policy at all. The
alternative, treating a missing policy as absent authorization and
allowing, would turn a typo in one environment variable into an open
door. This direction turns the same typo into an outage, which is the
failure an operator can see and fix.

## Why there is no cache

Both aggregates are folded from their streams on every call, so an
authorization decision is two small reads.
`keeper.authority.aggregates.policy.read` says why: these are a handful of
rows each, and a cache is not a line of code but an invalidation story.
When one is needed, a change that the next request does not see is the
bug it has to be designed against, and two tests fail first:
`test_a_grant_is_visible_to_the_very_next_decision` and
`test_a_deactivation_is_visible_to_the_very_next_decision`.

## Why a `Deny` carries prose and not a code

Two conditions means two reasons, and a machine-readable discriminator
saying which one failed would have no reader: every denial is a 403, the
surfaces do not branch, and what an operator counts is in the log, where
the two failures are separate events. The trigger for adding one is the
first caller that has to behave differently depending on why.
"""

from uuid import UUID

from keeper.access.aggregates.actor import load_actor
from keeper.authority.aggregates.policy import Permission, load_policy
from keeper.infrastructure.logging import get_logger
from keeper.infrastructure.ports import Allow, AllowAllAuthorize, Authorize, Deny
from keeper.infrastructure.ports.authorize import AuthzResult
from keeper.infrastructure.ports.event_store import EventStore
from keeper.infrastructure.settings import Settings
from keeper.shared.reserved_ids import NIL_SENTINEL_ID

_log = get_logger(__name__)


class PolicyAuthorize:
    """Allow a command when the configured policy holds the exact pair."""

    def __init__(self, event_store: EventStore, policy_id: UUID) -> None:
        self._event_store = event_store
        self._policy_id = policy_id

    async def authorize(
        self,
        principal_id: UUID,
        command_name: str,
        surface_id: UUID = NIL_SENTINEL_ID,
    ) -> AuthzResult:
        """Decide one command.

        `surface_id` is accepted and not consulted. No aggregate models a
        surface, so a policy cannot yet say "this principal, this
        command, but only over HTTP". Taking the argument and ignoring it
        is what lets that arrive as a change to this adapter rather than
        as a change to every call site.

        The denial reason names the command and never the policy. A
        caller already knows which command they sent, and the policy id
        is deployment detail that would be going to somebody this
        deployment has just refused. It goes to the log instead.
        """
        policy = await load_policy(self._event_store, self._policy_id)
        if policy is None:
            _log.error(
                "authz.policy_missing",
                policy_id=str(self._policy_id),
                command_name=command_name,
                principal_id=str(principal_id),
            )
            return Deny(reason="no policy is configured for this deployment")

        if Permission(principal_id=principal_id, command_name=command_name) not in (
            policy.permissions
        ):
            _log.info(
                "authz.denied",
                policy_id=str(self._policy_id),
                command_name=command_name,
                principal_id=str(principal_id),
                surface_id=str(surface_id),
            )
            return Deny(reason=f"not permitted to issue {command_name}")

        actor = await load_actor(self._event_store, principal_id)
        if actor is None:
            _log.info(
                "authz.denied_no_actor",
                command_name=command_name,
                principal_id=str(principal_id),
                surface_id=str(surface_id),
            )
            return Deny(reason="no actor is registered under this principal")
        if not actor.active:
            _log.info(
                "authz.denied_inactive_actor",
                command_name=command_name,
                principal_id=str(principal_id),
                surface_id=str(surface_id),
            )
            return Deny(reason="this actor is not active")

        return Allow()


def build_authorize(settings: Settings, event_store: EventStore) -> Authorize:
    """Build the authorization adapter this deployment should run.

    Satisfies `AuthorizeFactory`. A policy is folded from the event store
    like any other aggregate, so the store and the configured policy id are
    the whole of what deciding takes.

    Returns `AllowAllAuthorize` when no policy is configured. That is
    the bootstrap and the local-development posture, and it is refused
    on a production tier by `build_kernel`, not here: a factory that
    knew which tiers were permissive would be a second place deciding
    what this deployment is.
    """
    if settings.authz_policy_id is None:
        return AllowAllAuthorize()
    return PolicyAuthorize(event_store, settings.authz_policy_id)


__all__ = ["PolicyAuthorize", "build_authorize"]
