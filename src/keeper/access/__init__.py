"""Access bounded context.

Owns identity: who this system knows about. Not authorization, which is
the separate question of what a known party may do, and which nothing in
this repository answers yet.

The vocabulary is split on purpose, and the split is load-bearing:

    actor      an ENTITY. a party this system has a record of.
               has its own stream, and its own id.

    principal  a ROLE. whoever is making the call being handled.
               lives in the event envelope, on every event.

They are the same UUID whenever an actor is the one acting, and naming
them apart is what keeps a single event row readable: the envelope's
principal is who did it, and an id in the payload is who it was done to.
"""

from keeper.access.aggregates.actor import Actor, load_actor
from keeper.access.errors import UnauthorizedError
from keeper.access.routes import register_access_routes
from keeper.access.tools import register_access_tools
from keeper.access.wire import AccessHandlers, wire_access

__all__ = [
    "AccessHandlers",
    "Actor",
    "UnauthorizedError",
    "load_actor",
    "register_access_routes",
    "register_access_tools",
    "wire_access",
]
