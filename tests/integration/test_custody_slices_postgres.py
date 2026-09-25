"""The Custody slices, driven end to end against a real Postgres.

Every other test of this context runs on `InMemoryEventStore`, which
hands back the very objects it was given. Two things here are not proven
by that.

The external reference is the first. In state it is a value object; in a
row it is two strings inside a JSONB document that went out through a
serialiser and came back through a codec. A dataset that folds correctly
from a pair it never serialised proves nothing about the one a deployed
system reads back, and that pair is the only thing on the record a reader
can act on.

The cross-context read is the second, and it is the reason this file
exists rather than leaning on the sibling's. `register_dataset` loads a
run out of a different stream type in the same table. In memory those are
two dictionary keys; in Postgres it is a query that has to name the right
stream type, and a query naming the wrong one finds nothing and reports a
run that exists as missing.

The queries below spell `"Dataset"` as a literal rather than using
`DATASET_STREAM_TYPE`. That is the only independent side these tests
have: a query built from the writer's own constant agrees with the writer
however wrong the constant is.

The handlers come from `wire_custody`, not from `bind`, so these go
through the same composition the application boots: tracing and the
idempotency wrapper.
"""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import asyncpg
import pytest

from keeper.custody import wire_custody
from keeper.custody.aggregates.dataset import DatasetNotFoundError, load_dataset
from keeper.custody.features.get_dataset import GetDataset
from keeper.custody.features.register_dataset import RegisterDataset
from keeper.execution import wire_execution
from keeper.execution.aggregates.execution import ExecutionNotFoundError, load_execution
from keeper.execution.aggregates.procedure import AcquireStep
from keeper.execution.features.define_plan import DefinePlan
from keeper.execution.features.define_procedure import DefineProcedure
from keeper.execution.features.dispatch_execution import DispatchExecution
from keeper.infrastructure.deps import make_postgres_kernel
from keeper.infrastructure.kernel import Kernel
from keeper.infrastructure.ports import AllowAllAuthorize
from keeper.infrastructure.ports.clock import SystemClock
from keeper.infrastructure.ports.id_generator import UUIDv7Generator
from keeper.infrastructure.settings import Settings
from keeper.shared.identifier import Identifier

pytestmark = pytest.mark.integration

_WHEN = datetime(2026, 9, 19, 14, 30, tzinfo=UTC)
_REF = Identifier(scheme="tiled-node-path", value="raw/636de04a-2e43-4c1b")
_SCHEMA: dict[str, Any] = {"$schema": "https://json-schema.org/draft/2020-12/schema"}


@pytest.fixture
def kernel(db_pool: asyncpg.Pool) -> Kernel:
    """A kernel over the real pool, built the way the application builds one."""
    return make_postgres_kernel(
        db_pool,
        settings=Settings(app_env="test"),
        clock=SystemClock(),
        id_generator=UUIDv7Generator(),
        authz=AllowAllAuthorize(),
    )


async def _an_acquisition(deps: Kernel) -> tuple[UUID, UUID]:
    """Compose a one-step procedure, dispatch it, and return both ids.

    A dataset names the step that produced it, and a step exists only
    inside an execution, so the whole chain has to be real for the
    registering handler's check to have anything to find.
    """
    handlers = wire_execution(deps)
    plan_id = await handlers.define_plan(
        DefinePlan(name="count", parameters_schema=_SCHEMA),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )
    procedure_id = await handlers.define_procedure(
        DefineProcedure(
            name="one_scan",
            beamline="2-bm",
            steps=(AcquireStep(plan_id=plan_id, parameters={}, scopes=("2bmb:det:",)),),
        ),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )
    execution_id = await handlers.dispatch_execution(
        DispatchExecution(procedure_id=procedure_id),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )
    execution = await load_execution(deps.event_store, execution_id)
    assert execution is not None
    return execution_id, execution.steps[0].id


async def test_a_registered_dataset_reads_back_through_a_real_round_trip(
    kernel: Kernel,
) -> None:
    execution_id, step_id = await _an_acquisition(kernel)
    custody = wire_custody(kernel)

    dataset_id = await custody.register_dataset(
        RegisterDataset(
            execution_id=execution_id, step_id=step_id, external_ref=_REF, occurred_at=_WHEN
        ),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )

    dataset = await custody.get_dataset(
        GetDataset(dataset_id=dataset_id),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )
    assert (dataset.execution_id, dataset.step_id) == (execution_id, step_id)
    assert dataset.external_ref == _REF


async def test_the_reference_survives_the_jsonb_round_trip_as_two_strings(
    kernel: Kernel, db_pool: asyncpg.Pool
) -> None:
    """Read the row itself, not the fold, so the payload shape is pinned.

    A value object that rebuilt correctly from a payload this test never
    looked at would pass the case above while storing anything at all.
    """
    execution_id, step_id = await _an_acquisition(kernel)
    custody = wire_custody(kernel)
    dataset_id = await custody.register_dataset(
        RegisterDataset(execution_id=execution_id, step_id=step_id, external_ref=_REF),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )

    rows = await db_pool.fetch(
        "SELECT event_type, payload FROM events WHERE stream_type = 'Dataset' "
        "AND stream_id = $1 ORDER BY version",
        dataset_id,
    )

    assert [row["event_type"] for row in rows] == ["DatasetRegistered"]
    # The pool's codec already decodes JSONB, so the payload arrives as a
    # dict. Reading it as text here would be testing this file's guess
    # about the codec rather than what the column holds.
    payload = rows[0]["payload"]
    assert payload["external_ref_scheme"] == "tiled-node-path"
    assert payload["external_ref_value"] == "raw/636de04a-2e43-4c1b"
    assert payload["step_id"] == str(step_id)


async def test_the_run_a_dataset_cites_is_found_across_the_stream_types(
    kernel: Kernel,
) -> None:
    """The cross-context load, against the table both contexts share.

    Runs and datasets are different stream types in one `events` table,
    so a loader querying the wrong one reports a run that exists as
    missing. In memory that mistake is invisible.
    """
    execution_id, step_id = await _an_acquisition(kernel)
    custody = wire_custody(kernel)

    dataset_id = await custody.register_dataset(
        RegisterDataset(execution_id=execution_id, step_id=step_id, external_ref=_REF),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )

    assert dataset_id is not None


async def test_citing_a_step_that_does_not_exist_writes_nothing(
    kernel: Kernel, db_pool: asyncpg.Pool
) -> None:
    custody = wire_custody(kernel)

    with pytest.raises(ExecutionNotFoundError):
        await custody.register_dataset(
            RegisterDataset(execution_id=uuid4(), step_id=uuid4(), external_ref=_REF),
            principal_id=uuid4(),
            correlation_id=uuid4(),
        )

    count = await db_pool.fetchval("SELECT count(*) FROM events WHERE stream_type = 'Dataset'")
    assert count == 0


async def test_reading_an_unregistered_dataset_is_refused(kernel: Kernel) -> None:
    custody = wire_custody(kernel)

    with pytest.raises(DatasetNotFoundError):
        await custody.get_dataset(
            GetDataset(dataset_id=uuid4()),
            principal_id=uuid4(),
            correlation_id=uuid4(),
        )


async def test_a_replayed_key_returns_the_first_dataset_rather_than_a_second(
    kernel: Kernel, db_pool: asyncpg.Pool
) -> None:
    """The guard against a redelivered report, against the real key store.

    Nothing in this context refuses a duplicate on its own, so this is
    the only thing standing between at-least-once delivery and two
    records of one body of data. The in-memory idempotency store is a
    dictionary; this is the composite primary key doing the work.
    """
    execution_id, step_id = await _an_acquisition(kernel)
    custody = wire_custody(kernel)
    command = RegisterDataset(execution_id=execution_id, step_id=step_id, external_ref=_REF)
    principal_id = uuid4()
    key = f"register-dataset:{_REF.value}"

    first = await custody.register_dataset(
        command, principal_id=principal_id, correlation_id=uuid4(), idempotency_key=key
    )
    second = await custody.register_dataset(
        command, principal_id=principal_id, correlation_id=uuid4(), idempotency_key=key
    )

    assert first == second
    count = await db_pool.fetchval("SELECT count(*) FROM events WHERE stream_type = 'Dataset'")
    assert count == 1


async def test_a_dataset_the_store_holds_is_reachable_by_its_own_loader(
    kernel: Kernel,
) -> None:
    """The aggregate's loader, not the slice's, against real rows."""
    execution_id, step_id = await _an_acquisition(kernel)
    custody = wire_custody(kernel)
    dataset_id = await custody.register_dataset(
        RegisterDataset(execution_id=execution_id, step_id=step_id, external_ref=_REF),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )

    dataset = await load_dataset(kernel.event_store, dataset_id)

    assert dataset is not None
    assert dataset.id == dataset_id
