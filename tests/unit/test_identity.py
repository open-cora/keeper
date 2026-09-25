"""The attribution NewType aliases.

Small, but the module makes two claims worth holding it to: the aliases are
distinct to a type checker, and free at runtime. Only the second is
assertable here; the first is what pyright enforces over the whole tree.
"""

from uuid import UUID, uuid4

import pytest

from keeper.shared.identity import ActorId, AgentId

pytestmark = pytest.mark.unit


def test_actor_id_is_an_identity_function_at_runtime() -> None:
    """Zero-cost is the stated tradeoff for the type-check-time distinction."""
    raw = uuid4()
    wrapped = ActorId(raw)
    assert wrapped is raw
    assert isinstance(wrapped, UUID)


def test_agent_id_is_an_identity_function_at_runtime() -> None:
    raw = uuid4()
    assert AgentId(raw) is raw


def test_the_two_aliases_are_distinct_objects_so_a_checker_can_tell_them_apart() -> None:
    """Value-equal at runtime, different types to pyright, which is the whole design."""
    assert ActorId is not AgentId
    shared_uuid = uuid4()
    assert ActorId(shared_uuid) == AgentId(shared_uuid)
