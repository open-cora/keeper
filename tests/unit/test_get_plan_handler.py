"""The read handler, against in-process stores.

A read decides nothing, so what is left to check is the two things a
read can still get wrong: answering a caller who was refused, and
answering `None` where the surfaces both want a refusal.
"""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest

from keeper.execution.aggregates.plan import PlanName, PlanNotFoundError
from keeper.execution.errors import UnauthorizedError
from keeper.execution.features.define_plan import DefinePlan
from keeper.execution.features.define_plan import bind as bind_define
from keeper.execution.features.get_plan import GetPlan, bind
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


class _Ids:
    def new_id(self) -> UUID:
        return uuid4()


class _DenyAllAuthorize:
    async def authorize(
        self,
        principal_id: UUID,
        command_name: str,
        surface_id: UUID = NIL_SENTINEL_ID,
    ) -> AuthzResult:
        _ = (principal_id, command_name, surface_id)
        return Deny(reason="not on the list")


def _kernel(*, authz: object | None = None) -> Kernel:
    return make_inmemory_kernel(
        settings=Settings(app_env="test"),
        clock=_FixedClock(),
        id_generator=_Ids(),
        authz=authz or AllowAllAuthorize(),  # pyright: ignore[reportArgumentType]
        event_store=InMemoryEventStore(),
    )


async def test_reading_a_plan_gives_back_what_was_defined() -> None:
    deps = _kernel()
    plan_id = await bind_define(deps)(
        DefinePlan(name="count", parameters_schema=_SCHEMA),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )

    plan = await bind(deps)(GetPlan(plan_id=plan_id), principal_id=uuid4(), correlation_id=uuid4())

    assert plan.id == plan_id
    assert plan.name == PlanName("count")
    assert plan.parameters_schema == _SCHEMA


async def test_reading_a_plan_that_was_never_defined_is_refused() -> None:
    """Not `None`. Both surfaces want a refusal, so the handler raises.

    Returning `None` would put the same two-line translation in the route
    and in the tool, which is two places for them to drift apart on what
    a missing plan means.
    """
    with pytest.raises(PlanNotFoundError):
        await bind(_kernel())(
            GetPlan(plan_id=uuid4()), principal_id=uuid4(), correlation_id=uuid4()
        )


async def test_a_denied_caller_cannot_read_a_plan() -> None:
    """A read is gated too, and the reason is not symmetry.

    A plan says what this system can be asked to run and what a request
    has to look like, so reading one tells a caller the shape of a
    command they may not be permitted to send.
    """
    deps = _kernel()
    plan_id = await bind_define(deps)(
        DefinePlan(name="count", parameters_schema=_SCHEMA),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )
    refusing = bind(_kernel(authz=_DenyAllAuthorize()))

    with pytest.raises(UnauthorizedError, match="not on the list"):
        await refusing(GetPlan(plan_id=plan_id), principal_id=uuid4(), correlation_id=uuid4())
