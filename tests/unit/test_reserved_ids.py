"""The reserved UUID constants are distinct from one another.

Every one of them is a namespace constant rather than a foreign key:
nothing seeds a row at any of these ids. What they have to do is differ.

Two separate reasons, and neither is checked by anything else. The
idempotency cache key is `(principal_id, key, surface_id)`, so two
surfaces sharing a value would let the same key replayed over HTTP and
over MCP collide and return each other's answers. And a principal id
equal to `NIL_SENTINEL_ID` cannot be told apart from "unspecified",
which is the confusion the system principal was moved off the nil UUID
to end.

Written as a set comparison rather than a list of pairs so a constant
added later is covered by existing code instead of by someone
remembering to add a pair.
"""

import pytest

from keeper.shared.reserved_ids import (
    NIL_SENTINEL_ID,
    SYSTEM_HTTP_SURFACE_ID,
    SYSTEM_MCP_STDIO_SURFACE_ID,
    SYSTEM_MCP_STREAMABLE_HTTP_SURFACE_ID,
    SYSTEM_PRINCIPAL_ID,
)

pytestmark = pytest.mark.unit

RESERVED = {
    "NIL_SENTINEL_ID": NIL_SENTINEL_ID,
    "SYSTEM_PRINCIPAL_ID": SYSTEM_PRINCIPAL_ID,
    "SYSTEM_HTTP_SURFACE_ID": SYSTEM_HTTP_SURFACE_ID,
    "SYSTEM_MCP_STDIO_SURFACE_ID": SYSTEM_MCP_STDIO_SURFACE_ID,
    "SYSTEM_MCP_STREAMABLE_HTTP_SURFACE_ID": SYSTEM_MCP_STREAMABLE_HTTP_SURFACE_ID,
}


def test_every_reserved_id_differs_from_every_other() -> None:
    assert len(set(RESERVED.values())) == len(RESERVED), (
        "Two reserved ids share a value:\n  "
        + "\n  ".join(f"{name} = {value}" for name, value in sorted(RESERVED.items()))
    )


def test_the_system_principal_is_not_the_nil_sentinel() -> None:
    """Called out on its own because it is the pair that was once equal.

    The set check above would catch it, but not say which collision
    mattered or why, and this one has a reason the others do not share:
    a policy granting the system account must not read as a policy
    granting nobody in particular.
    """
    assert SYSTEM_PRINCIPAL_ID != NIL_SENTINEL_ID
