"""The registering handler, against in-process stores.

The first handler in this tree that reads an aggregate in another bounded
context, so the cases that matter are the ones about that read: that a
run which is not there is the handler's refusal rather than the decider's,
and that nothing is written when it fires.
"""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest

from keeper.custody.aggregates.dataset import DATASET_STREAM_TYPE, load_dataset
from keeper.custody.errors import UnauthorizedError
from keeper.custody.features.register_dataset import RegisterDataset, bind
from keeper.execution.aggregates.execution import (
    ExecutionNotFoundError,
    ExecutionStepNotFoundError,
    load_execution,
)
from keeper.execution.aggregates.procedure import AcquireStep
from keeper.execution.features.define_plan import DefinePlan
from keeper.execution.features.define_plan import bind as bind_define_plan
from keeper.execution.features.define_procedure import DefineProcedure
from keeper.execution.features.define_procedure import bind as bind_define_procedure
from keeper.execution.features.dispatch_execution import DispatchExecution
from keeper.execution.features.dispatch_execution import bind as bind_dispatch_execution
from keeper.infrastructure.adapters.in_memory_event_store import InMemoryEventStore
from keeper.infrastructure.deps import make_inmemory_kernel
from keeper.infrastructure.kernel import Kernel
from keeper.infrastructure.ports import AllowAllAuthorize, Deny
from keeper.infrastructure.ports.authorize import AuthzResult
from keeper.infrastructure.settings import Settings
from keeper.shared.identifier import Identifier
from keeper.shared.reserved_ids import NIL_SENTINEL_ID

pytestmark = pytest.mark.unit

_WHEN = datetime(2026, 9, 19, 14, 30, tzinfo=UTC)
_CLOCK_NOW = datetime(2026, 9, 19, 9, 0, tzinfo=UTC)
"""What the clock says, deliberately not the time any caller reports."""
_REF = Identifier(scheme="tiled-node-path", value="raw/636de04a-2e43-4c1b")
_SCHEMA: dict[str, Any] = {"$schema": "https://json-schema.org/draft/2020-12/schema"}


class _FixedClock:
    def now(self) -> datetime:
        return _CLOCK_NOW


class _Uuid4IdGenerator:
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
        return Deny(reason="not granted in this test")


def _kernel(*, authz: object | None = None) -> Kernel:
    return make_inmemory_kernel(
        settings=Settings(app_env="test"),
        clock=_FixedClock(),
        id_generator=_Uuid4IdGenerator(),
        authz=authz or AllowAllAuthorize(),  # pyright: ignore[reportArgumentType]
        event_store=InMemoryEventStore(),
    )


async def _an_acquisition(deps: Kernel) -> tuple[UUID, UUID]:
    """A plan, a procedure that acquires it, and one dispatch of that.

    The whole chain, because the handler checks that the execution holds
    the step. A step is an entity inside that aggregate rather than a
    stream of its own, so there is nothing to stub short of dispatching.
    """
    plan_id = await bind_define_plan(deps)(
        DefinePlan(name="count", parameters_schema=_SCHEMA),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )
    procedure_id = await bind_define_procedure(deps)(
        DefineProcedure(
            name="one_scan",
            beamline="2-bm",
            steps=(AcquireStep(plan_id=plan_id, parameters={}, scopes=("2bmb:det:",)),),
        ),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )
    execution_id = await bind_dispatch_execution(deps)(
        DispatchExecution(procedure_id=procedure_id),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )
    execution = await load_execution(deps.event_store, execution_id)
    assert execution is not None
    return execution_id, execution.steps[0].id


async def test_registering_returns_the_id_the_dataset_can_be_loaded_by() -> None:
    deps = _kernel()
    execution_id, step_id = await _an_acquisition(deps)

    dataset_id = await bind(deps)(
        RegisterDataset(execution_id=execution_id, step_id=step_id, external_ref=_REF),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )

    dataset = await load_dataset(deps.event_store, dataset_id)
    assert dataset is not None
    assert (dataset.execution_id, dataset.step_id) == (execution_id, step_id)
    assert dataset.external_ref == _REF


async def test_naming_an_execution_that_does_not_exist_is_not_found() -> None:
    deps = _kernel()

    with pytest.raises(ExecutionNotFoundError):
        await bind(deps)(
            RegisterDataset(execution_id=uuid4(), step_id=uuid4(), external_ref=_REF),
            principal_id=uuid4(),
            correlation_id=uuid4(),
        )


async def test_naming_a_step_the_execution_does_not_hold_is_not_found() -> None:
    """The second check a step reference costs. The execution is real and
    the step is not, which a reference to the traversal alone could never
    have caught."""
    deps = _kernel()
    execution_id, _step_id = await _an_acquisition(deps)

    with pytest.raises(ExecutionStepNotFoundError):
        await bind(deps)(
            RegisterDataset(execution_id=execution_id, step_id=uuid4(), external_ref=_REF),
            principal_id=uuid4(),
            correlation_id=uuid4(),
        )


async def test_an_execution_that_does_not_exist_leaves_no_stream_behind() -> None:
    deps = _kernel()
    store = deps.event_store
    assert isinstance(store, InMemoryEventStore)

    with pytest.raises(ExecutionNotFoundError):
        await bind(deps)(
            RegisterDataset(execution_id=uuid4(), step_id=uuid4(), external_ref=_REF),
            principal_id=uuid4(),
            correlation_id=uuid4(),
        )

    assert store.stream_ids(DATASET_STREAM_TYPE) == []


async def test_a_denied_caller_gets_an_error_and_the_execution_is_never_read() -> None:
    """The gate runs before the sibling load, so a refused caller cannot
    use this slice to learn whether an execution id exists."""
    deps = _kernel(authz=_DenyAllAuthorize())

    with pytest.raises(UnauthorizedError):
        await bind(deps)(
            RegisterDataset(execution_id=uuid4(), step_id=uuid4(), external_ref=_REF),
            principal_id=uuid4(),
            correlation_id=uuid4(),
        )


async def test_a_reported_time_is_what_the_event_carries() -> None:
    deps = _kernel()
    execution_id, step_id = await _an_acquisition(deps)
    store = deps.event_store
    assert isinstance(store, InMemoryEventStore)

    dataset_id = await bind(deps)(
        RegisterDataset(
            execution_id=execution_id, step_id=step_id, external_ref=_REF, occurred_at=_WHEN
        ),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )

    rows, _version = await store.load(DATASET_STREAM_TYPE, dataset_id)
    assert [row.occurred_at for row in rows] == [_WHEN]


async def test_omitting_the_time_stamps_the_moment_the_report_arrived() -> None:
    deps = _kernel()
    execution_id, step_id = await _an_acquisition(deps)
    store = deps.event_store
    assert isinstance(store, InMemoryEventStore)

    dataset_id = await bind(deps)(
        RegisterDataset(execution_id=execution_id, step_id=step_id, external_ref=_REF),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )

    rows, _version = await store.load(DATASET_STREAM_TYPE, dataset_id)
    assert [row.occurred_at for row in rows] == [_CLOCK_NOW]


async def test_the_appended_event_records_the_principal_that_issued_the_command() -> None:
    deps = _kernel()
    execution_id, step_id = await _an_acquisition(deps)
    principal_id = uuid4()
    store = deps.event_store
    assert isinstance(store, InMemoryEventStore)

    dataset_id = await bind(deps)(
        RegisterDataset(execution_id=execution_id, step_id=step_id, external_ref=_REF),
        principal_id=principal_id,
        correlation_id=uuid4(),
    )

    rows, _version = await store.load(DATASET_STREAM_TYPE, dataset_id)
    assert [row.principal_id for row in rows] == [principal_id]


async def test_two_datasets_may_cite_one_run() -> None:
    """One per run is the producer's policy, not the model's.

    Pinned here because the alternative was a stream id derived from the
    run id, which would have made one-per-run permanent from the first
    migration. It is not, so a second dataset lands on its own stream.
    """
    deps = _kernel()
    execution_id, step_id = await _an_acquisition(deps)
    handler = bind(deps)

    first = await handler(
        RegisterDataset(execution_id=execution_id, step_id=step_id, external_ref=_REF),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )
    second = await handler(
        RegisterDataset(
            execution_id=execution_id,
            step_id=step_id,
            external_ref=Identifier(scheme="tiled-node-path", value="proc/636de04a"),
        ),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )

    assert first != second
