"""The definition handler, against in-process stores.

Create-style, so there is no load to get wrong and the interesting parts
are at the edges: that authorization is settled before anything is minted,
and that what comes back is an id the plan can actually be read by.
"""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest

from keeper.execution.aggregates.plan import (
    PLAN_STREAM_TYPE,
    InvalidPlanParametersSchemaError,
    Plan,
    PlanName,
    load_plan,
)
from keeper.execution.errors import UnauthorizedError
from keeper.execution.features.define_plan import DefinePlan, bind
from keeper.infrastructure.adapters.in_memory_event_store import InMemoryEventStore
from keeper.infrastructure.deps import make_inmemory_kernel
from keeper.infrastructure.kernel import Kernel
from keeper.infrastructure.ports import AllowAllAuthorize, Deny
from keeper.infrastructure.ports.authorize import AuthzResult
from keeper.infrastructure.settings import Settings
from keeper.shared.reserved_ids import NIL_SENTINEL_ID

pytestmark = pytest.mark.unit

_WHEN = datetime(2026, 9, 18, 9, 30, tzinfo=UTC)

_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {"exposure_seconds": {"type": "number", "minimum": 0}},
    "required": ["exposure_seconds"],
}


class _FixedClock:
    def now(self) -> datetime:
        return _WHEN


class _CountingIdGenerator:
    """Hands out ids and remembers them, so a test can assert none was minted."""

    def __init__(self) -> None:
        self.issued: list[UUID] = []

    def new_id(self) -> UUID:
        minted = uuid4()
        self.issued.append(minted)
        return minted


class _DenyAllAuthorize:
    async def authorize(
        self,
        principal_id: UUID,
        command_name: str,
        surface_id: UUID = NIL_SENTINEL_ID,
    ) -> AuthzResult:
        _ = (principal_id, command_name, surface_id)
        return Deny(reason="not on the list")


def _kernel(
    *,
    authz: object | None = None,
    event_store: InMemoryEventStore | None = None,
) -> Kernel:
    return make_inmemory_kernel(
        settings=Settings(app_env="test"),
        clock=_FixedClock(),
        id_generator=_CountingIdGenerator(),
        authz=authz or AllowAllAuthorize(),  # pyright: ignore[reportArgumentType]
        event_store=event_store or InMemoryEventStore(),
    )


async def test_defining_returns_the_id_the_plan_can_be_loaded_by() -> None:
    deps = _kernel()
    handler = bind(deps)

    plan_id = await handler(
        DefinePlan(name="count", parameters_schema=_SCHEMA),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )

    assert await load_plan(deps.event_store, plan_id) == Plan(
        id=plan_id, name=PlanName("count"), parameters_schema=_SCHEMA
    )


async def test_the_appended_event_records_the_principal_that_issued_the_command() -> None:
    deps = _kernel()
    handler = bind(deps)
    caller = uuid4()

    plan_id = await handler(
        DefinePlan(name="count", parameters_schema=_SCHEMA),
        principal_id=caller,
        correlation_id=uuid4(),
    )

    rows, _version = await deps.event_store.load(PLAN_STREAM_TYPE, plan_id)
    assert rows[0].principal_id == caller


async def test_a_denied_caller_gets_an_error_and_writes_nothing() -> None:
    deps = _kernel(authz=_DenyAllAuthorize())
    handler = bind(deps)

    with pytest.raises(UnauthorizedError, match="not on the list"):
        await handler(
            DefinePlan(name="count", parameters_schema=_SCHEMA),
            principal_id=uuid4(),
            correlation_id=uuid4(),
        )

    generator = deps.id_generator
    assert isinstance(generator, _CountingIdGenerator)
    assert generator.issued == [], "authorization must be decided before an id is minted"


async def test_a_refused_schema_leaves_no_stream_behind() -> None:
    """The decider raises after the id is minted, and before the append.

    An id is spent either way, which costs nothing, but a stream must not
    be: a plan whose genesis was refused should be absent, not present
    and empty. Loading by the minted id is the only way to tell those two
    apart from outside.
    """
    deps = _kernel()
    handler = bind(deps)

    with pytest.raises(InvalidPlanParametersSchemaError):
        await handler(
            DefinePlan(name="count", parameters_schema={"type": "object"}),
            principal_id=uuid4(),
            correlation_id=uuid4(),
        )

    generator = deps.id_generator
    assert isinstance(generator, _CountingIdGenerator)
    assert len(generator.issued) == 1, "the id was minted before the decision refused"
    assert await load_plan(deps.event_store, generator.issued[0]) is None


async def test_two_plans_may_share_a_name_and_stay_separate_records() -> None:
    """Nothing enforces a unique name, and the two must not collide.

    One routine constrained two ways is two plans. If both landed on one
    stream the second definition would be refused as a duplicate genesis,
    which is the failure this asserts is absent.
    """
    deps = _kernel()
    handler = bind(deps)
    loose = {"$schema": "https://json-schema.org/draft/2020-12/schema"}

    first = await handler(
        DefinePlan(name="count", parameters_schema=_SCHEMA),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )
    second = await handler(
        DefinePlan(name="count", parameters_schema=loose),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )

    assert first != second
    one, two = await load_plan(deps.event_store, first), await load_plan(deps.event_store, second)
    assert one is not None
    assert two is not None
    assert one.name == two.name
    assert one.parameters_schema != two.parameters_schema
