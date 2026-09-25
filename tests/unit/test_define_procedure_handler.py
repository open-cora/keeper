"""The composition handler, against in-process stores.

Create-style, so there is no load of its own stream to get wrong. What is
interesting here is the reading it does of OTHER streams: a procedure
cites plans, the decider is pure and cannot fetch them, and this is the
first handler in the tree that loads several siblings rather than one.
"""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest

from keeper.execution.aggregates.plan import PlanNotFoundError
from keeper.execution.aggregates.procedure import (
    PROCEDURE_STREAM_TYPE,
    AcquireStep,
    MoveStep,
    ProcedureName,
    load_procedure,
)
from keeper.execution.errors import UnauthorizedError
from keeper.execution.features.define_plan import DefinePlan
from keeper.execution.features.define_plan import bind as bind_define_plan
from keeper.execution.features.define_procedure import DefineProcedure, bind
from keeper.infrastructure.adapters.in_memory_event_store import InMemoryEventStore
from keeper.infrastructure.deps import make_inmemory_kernel
from keeper.infrastructure.kernel import Kernel
from keeper.infrastructure.ports import AllowAllAuthorize, Deny
from keeper.infrastructure.ports.authorize import AuthzResult
from keeper.infrastructure.settings import Settings
from keeper.shared.reserved_ids import NIL_SENTINEL_ID

pytestmark = pytest.mark.unit

_WHEN = datetime(2026, 9, 24, 11, 0, tzinfo=UTC)

_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {"exposure_seconds": {"type": "number", "minimum": 0}},
    "required": ["exposure_seconds"],
}


class _FixedClock:
    def now(self) -> datetime:
        return _WHEN


class _CountingEventStore(InMemoryEventStore):
    """Counts loads, so a test can assert a repeated plan is read once."""

    def __init__(self) -> None:
        super().__init__()
        self.loads: list[tuple[str, UUID]] = []

    async def load(self, stream_type: str, stream_id: UUID) -> tuple[list[Any], int]:  # pyright: ignore[reportIncompatibleMethodOverride]
        self.loads.append((stream_type, stream_id))
        return await super().load(stream_type, stream_id)


class _IdGenerator:
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


def _kernel(
    *,
    authz: object | None = None,
    event_store: InMemoryEventStore | None = None,
) -> Kernel:
    return make_inmemory_kernel(
        settings=Settings(app_env="test"),
        clock=_FixedClock(),
        id_generator=_IdGenerator(),  # pyright: ignore[reportArgumentType]
        authz=authz or AllowAllAuthorize(),  # pyright: ignore[reportArgumentType]
        event_store=event_store or InMemoryEventStore(),
    )


async def _a_plan(deps: Kernel) -> UUID:
    return await bind_define_plan(deps)(
        DefinePlan(name="count", parameters_schema=_SCHEMA),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )


async def test_composing_returns_the_id_the_procedure_can_be_loaded_by() -> None:
    deps = _kernel()
    plan_id = await _a_plan(deps)
    steps = (
        MoveStep(record="2bmb:m1", to=12.5),
        AcquireStep(
            plan_id=plan_id, parameters={"exposure_seconds": 0.2}, scopes=("2bmb:m1", "2bmb:det:")
        ),
    )

    procedure_id = await bind(deps)(
        DefineProcedure(name="tomography", beamline="2-bm", steps=steps),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )

    procedure = await load_procedure(deps.event_store, procedure_id)
    assert procedure is not None
    assert procedure.name == ProcedureName("tomography")
    assert tuple(composed.step for composed in procedure.steps) == steps
    assert len({composed.id for composed in procedure.steps}) == len(steps)


async def test_a_procedure_citing_a_plan_that_does_not_exist_is_refused() -> None:
    """The check the decider cannot make, because discovering an absence
    needs the store and a decider has none."""
    deps = _kernel()
    absent = uuid4()

    with pytest.raises(PlanNotFoundError):
        await bind(deps)(
            DefineProcedure(
                name="tomography",
                beamline="2-bm",
                steps=(AcquireStep(plan_id=absent, parameters={}, scopes=("2bmb:m1",)),),
            ),
            principal_id=uuid4(),
            correlation_id=uuid4(),
        )


async def test_the_same_plan_acquired_many_times_is_read_once() -> None:
    """A tomography procedure acquires the same plan at every sample
    position. Reading that stream once per step would make composing a
    routine cost a replay per step for no new information."""
    store = _CountingEventStore()
    deps = _kernel(event_store=store)
    plan_id = await _a_plan(deps)
    store.loads.clear()

    await bind(deps)(
        DefineProcedure(
            name="tomography",
            beamline="2-bm",
            steps=tuple(
                AcquireStep(
                    plan_id=plan_id,
                    parameters={"exposure_seconds": 0.2},
                    scopes=(f"2bmb:m{i}",),
                )
                for i in range(5)
            ),
        ),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )

    assert store.loads.count(("Plan", plan_id)) == 1


async def test_the_appended_event_records_the_principal_that_issued_the_command() -> None:
    deps = _kernel()
    caller = uuid4()

    procedure_id = await bind(deps)(
        DefineProcedure(
            name="tomography", beamline="2-bm", steps=(MoveStep(record="2bmb:m1", to=1.0),)
        ),
        principal_id=caller,
        correlation_id=uuid4(),
    )

    rows, _version = await deps.event_store.load(PROCEDURE_STREAM_TYPE, procedure_id)
    assert rows[0].principal_id == caller


async def test_a_denied_caller_gets_an_error_and_writes_nothing() -> None:
    store = InMemoryEventStore()
    deps = _kernel(authz=_DenyAllAuthorize(), event_store=store)

    with pytest.raises(UnauthorizedError, match="not on the list"):
        await bind(deps)(
            DefineProcedure(
                name="tomography", beamline="2-bm", steps=(MoveStep(record="2bmb:m1", to=1.0),)
            ),
            principal_id=uuid4(),
            correlation_id=uuid4(),
        )

    assert list(store.stream_ids(PROCEDURE_STREAM_TYPE)) == []


async def test_a_denied_caller_is_refused_before_any_plan_is_read() -> None:
    """Authorization settles first, so a caller who may not compose
    cannot use this endpoint to learn which plan ids exist."""
    store = _CountingEventStore()
    deps = _kernel(authz=_DenyAllAuthorize(), event_store=store)

    with pytest.raises(UnauthorizedError):
        await bind(deps)(
            DefineProcedure(
                name="tomography",
                beamline="2-bm",
                steps=(AcquireStep(plan_id=uuid4(), parameters={}, scopes=("2bmb:m1",)),),
            ),
            principal_id=uuid4(),
            correlation_id=uuid4(),
        )

    assert store.loads == []
