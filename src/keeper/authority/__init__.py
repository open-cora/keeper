"""Authority bounded context.

Owns authorization: what a known party may do. Not identity, which is
the separate question of who a party is, and which Access answers.

The two contexts split one sentence between them. Access says the
caller is somebody; Authority says that somebody may issue this command.
A deployment authorizes against exactly one policy, chosen by id in
settings, so this context holds a rulebook rather than a collection of
them.

The vocabulary distinction Access draws between an actor and a principal
carries over and gains a third term:

    principal   a ROLE. whoever is making the call being handled.
                lives in the event envelope, on every event.

    permission  a PAIR. one principal may issue one command.
                lives inside a policy, in the payload.

An event here therefore names principals twice over, and they mean
different things: the envelope's principal authored the rulebook, and
the principals inside its permissions are the ones being granted
something. Bootstrapping relies on the difference, because the party
that defines the first policy is running under no policy at all.
"""

from keeper.authority.adapters import PolicyAuthorize, build_authorize
from keeper.authority.aggregates.policy import Permission, Policy, load_policy
from keeper.authority.errors import UnauthorizedError
from keeper.authority.routes import register_authority_routes
from keeper.authority.tools import register_authority_tools
from keeper.authority.wire import AuthorityHandlers, wire_authority

__all__ = [
    "AuthorityHandlers",
    "Permission",
    "Policy",
    "PolicyAuthorize",
    "UnauthorizedError",
    "build_authorize",
    "load_policy",
    "register_authority_routes",
    "register_authority_tools",
    "wire_authority",
]
