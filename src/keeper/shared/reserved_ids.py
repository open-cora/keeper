"""The reserved UUID constants, and what each one means.

Five values, none of them a foreign key. Nothing seeds a row at any of
them; they are a namespace the system agrees on, so two parts of it can
mean the same thing by the same number.

They live in `keeper.shared`, which imports nothing, because of what
depended on them from where. They used to sit in
`keeper.infrastructure.request`, a module that imports FastAPI in order to
read headers off a live request. The `Authorize` port needed one of
them, so importing a domain port pulled a web framework in behind it,
and a pure decider could not name the system principal at all without
doing the same.

The grouping is by decade, so a reader can tell what kind of thing a
reserved id is from its number:

    ...0000     the nil sentinel, meaning unspecified
    ...0010+    principals
    ...0020+    arrival surfaces

`tests/unit/test_reserved_ids.py` pins that they stay distinct, which is
the one property all five rely on.
"""

from uuid import UUID

SYSTEM_PRINCIPAL_ID = UUID("00000000-0000-0000-0000-000000000010")
"""Fallback principal used when no `X-Principal-Id` header is supplied.

Deliberately NOT the nil UUID, which it used to be. `NIL_SENTINEL_ID`
below means "unspecified" on every axis the `Authorize` port takes, and
the system principal is the opposite of unspecified: it is a named
party a policy can grant or refuse by id. One value cannot carry both
meanings, and the place it breaks is a rulebook, where a permission
granted to the system account would be indistinguishable from one
granted to nobody in particular.

The reserved block groups by decade: `...0010` upward for principals,
`...0020` upward for arrival surfaces. Values here are namespace
constants, not foreign keys; nothing seeds a row at any of them.

Used only when `Settings.require_authenticated_principal` is False
(legacy dev / test posture). Production deployments behind an auth
proxy set the header on every request and turn the setting on so
header-absent requests are rejected at the boundary instead of
silently running as SYSTEM. Under a real authorize adapter with a
policy that does not permit `SYSTEM_PRINCIPAL_ID`, fallback-using
requests get 403 even with the setting off. That is defence in depth,
and it is unpinned until a BC supplies a real authorize adapter to
test it against.
"""


NIL_SENTINEL_ID = UUID(int=0)
"""Canonical unspecified-id sentinel.

`UUID(int=0)` means "unspecified" wherever the `Authorize` port takes a
UUID axis: `surface_id`, and any axis added later. It is never a
principal; `SYSTEM_PRINCIPAL_ID` above is a named party and carries its
own value precisely so the two cannot be confused.

It is NOT a wildcard, and an authorize adapter that reads it as one
would widen every policy written against it. A policy bound to
`surface_id=NIL` is meant to match only a call that also presents NIL.
`AllowAllAuthorize` permits everything and so cannot express the
difference; the rule is stated here because the first adapter that
actually evaluates policy has to honour it, and by then the constant
will be threaded through call sites that predate it.

One name covers every axis on purpose. A per-axis constant reads as a
default for that axis, which invites a reader to supply it where the
value is genuinely unknown rather than genuinely unspecified."""


SYSTEM_HTTP_SURFACE_ID = UUID("00000000-0000-0000-0000-000000000020")
SYSTEM_MCP_STDIO_SURFACE_ID = UUID("00000000-0000-0000-0000-000000000021")
SYSTEM_MCP_STREAMABLE_HTTP_SURFACE_ID = UUID("00000000-0000-0000-0000-000000000022")
"""Arrival-Surface UUIDs, resolved by `get_surface_id` and
`get_mcp_surface_id` below, which are their only consumers today.

Nothing seeds them. No table in the baseline migration holds a surface
row, because no aggregate models an ingress surface yet, so these are
namespace constants rather than foreign keys. What they have to do
right now is stay DIFFERENT from each other: the idempotency cache key
is `(principal_id, key, surface_id)`, so the same key replayed over
HTTP and over MCP must not collide.

When a bounded context does model surfaces, it seeds rows at these ids
rather than minting new ones, and the constants become the shared
vocabulary between the record and the resolvers. They live here rather
than inside that context so every route and tool can resolve a surface
without importing it.
"""
__all__ = [
    "NIL_SENTINEL_ID",
    "SYSTEM_HTTP_SURFACE_ID",
    "SYSTEM_MCP_STDIO_SURFACE_ID",
    "SYSTEM_MCP_STREAMABLE_HTTP_SURFACE_ID",
    "SYSTEM_PRINCIPAL_ID",
]
