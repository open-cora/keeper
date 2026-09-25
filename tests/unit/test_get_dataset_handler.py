"""Reading a dataset back, against in-process stores.

A query slice, so there is nothing to decide and the cases are the three
answers it can give: the record, a refusal for an id nobody registered,
and a refusal for a caller who may not ask.
"""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest

from keeper.custody.aggregates.dataset import DatasetNotFoundError
from keeper.custody.errors import UnauthorizedError
from keeper.custody.features.get_dataset import GetDataset
from keeper.custody.features.get_dataset import bind as bind_get_dataset
from keeper.custody.features.register_dataset import RegisterDataset
from keeper.custody.features.register_dataset import bind as bind_register_dataset
from keeper.execution.aggregates.execution import load_execution
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

_CLOCK_NOW = datetime(2026, 9, 19, 9, 0, tzinfo=UTC)
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


async def _a_dataset(deps: Kernel) -> tuple[UUID, UUID]:
    """Register one dataset against a real acquisition, and hand back both ids.

    The whole chain has to be real, because the registering handler
    checks that the execution holds the step: a step is an entity inside
    that aggregate rather than a stream of its own, so there is nothing
    to fake short of dispatching something.
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
    step_id = execution.steps[0].id
    dataset_id = await bind_register_dataset(deps)(
        RegisterDataset(execution_id=execution_id, step_id=step_id, external_ref=_REF),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )
    return dataset_id, step_id


async def test_reading_a_registered_dataset_gives_its_step_and_reference() -> None:
    deps = _kernel()
    dataset_id, step_id = await _a_dataset(deps)

    dataset = await bind_get_dataset(deps)(
        GetDataset(dataset_id=dataset_id),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )

    assert dataset.id == dataset_id
    assert dataset.step_id == step_id
    assert dataset.external_ref == _REF


async def test_reading_an_unknown_id_is_not_found() -> None:
    deps = _kernel()

    with pytest.raises(DatasetNotFoundError):
        await bind_get_dataset(deps)(
            GetDataset(dataset_id=uuid4()),
            principal_id=uuid4(),
            correlation_id=uuid4(),
        )


async def test_a_denied_caller_learns_nothing_about_the_dataset() -> None:
    """Reading is gated, because a record saying where a run's data is
    kept is close to the strongest thing this context can tell anybody."""
    deps = _kernel()
    dataset_id, _step_id = await _a_dataset(deps)
    denied = _kernel(authz=_DenyAllAuthorize())

    with pytest.raises(UnauthorizedError):
        await bind_get_dataset(denied)(
            GetDataset(dataset_id=dataset_id),
            principal_id=uuid4(),
            correlation_id=uuid4(),
        )
