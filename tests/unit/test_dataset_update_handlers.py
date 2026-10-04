"""The four handlers that add a later fact to a dataset already held.

All four append to a stream that already has rows, which is what
separates them from the genesis slice and is the whole of what this
file is for: that the version the load returned is the version the
append uses, and that a denied caller writes nothing.

One file for the four, because they share a fixture chain four calls
deep and the sibling context keeps its transition handlers together for
the same reason. Two of them say where the data can be read, the third
says what is inside it and the fourth says what somebody made of that,
which is a difference the deciders care about and these handlers do
not.
"""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest

from keeper.custody.aggregates.dataset import (
    DATASET_STREAM_TYPE,
    CopiedBy,
    Entry,
    Extent,
    Finding,
    Manifest,
    load_dataset,
)
from keeper.custody.features.record_dataset_finding import RecordDatasetFinding
from keeper.custody.features.record_dataset_finding import bind as bind_record_finding
from keeper.custody.features.register_dataset import RegisterDataset
from keeper.custody.features.register_dataset import bind as bind_register_dataset
from keeper.custody.features.register_dataset_address import RegisterDatasetAddress
from keeper.custody.features.register_dataset_address import bind as bind_register_address
from keeper.custody.features.register_dataset_manifest import RegisterDatasetManifest
from keeper.custody.features.register_dataset_manifest import bind as bind_register_manifest
from keeper.custody.features.withdraw_dataset_address import WithdrawDatasetAddress
from keeper.custody.features.withdraw_dataset_address import bind as bind_withdraw_address
from keeper.execution.aggregates.execution import load_execution
from keeper.execution.aggregates.procedure import RunStep
from keeper.execution.features.define_operation import DefineOperation
from keeper.execution.features.define_operation import bind as bind_define_operation
from keeper.execution.features.define_procedure import DefineProcedure
from keeper.execution.features.define_procedure import bind as bind_define_procedure
from keeper.execution.features.dispatch_execution import DispatchExecution
from keeper.execution.features.dispatch_execution import bind as bind_dispatch_execution
from keeper.infrastructure.adapters.in_memory_event_store import InMemoryEventStore
from keeper.infrastructure.deps import make_inmemory_kernel
from keeper.infrastructure.kernel import Kernel
from keeper.infrastructure.ports import AllowAllAuthorize, ConcurrencyError, Deny
from keeper.infrastructure.ports.authorize import AuthzResult
from keeper.infrastructure.ports.event_store import EventStore, NewEvent, StoredEvent
from keeper.infrastructure.settings import Settings
from keeper.shared.identifier import Identifier
from keeper.shared.reserved_ids import NIL_SENTINEL_ID
from keeper.shared.unauthorized import UnauthorizedError

pytestmark = pytest.mark.unit

_WHEN = datetime(2026, 9, 19, 14, 30, tzinfo=UTC)
_CLOCK_NOW = datetime(2026, 9, 19, 9, 0, tzinfo=UTC)
"""What the clock says, deliberately not the time any caller reports."""
_BEAMLINE = Identifier(scheme="posix-file", value="/local1/scan_034.h5")
_CENTRAL = Identifier(scheme="gpfs-file", value="/central/raw/scan_034.h5")
_A_MANIFEST = Manifest(
    convention="dxchange",
    entries=(
        Entry(
            path="/exchange/data",
            extent=Extent(shape=(1800, 2048, 2048), capacity=None, dtype="uint16"),
            role="projections",
        ),
    ),
)
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
        beamline: str | None = None,
    ) -> AuthzResult:
        _ = (principal_id, command_name, surface_id)
        return Deny(reason="not granted in this test")


class _RacingEventStore(InMemoryEventStore):
    """Lands a competing address between the handler's load and its append.

    The race is injected from `load`, not from `append`, and that
    placement is the whole point. A store that raced inside `append`
    would make the handler conflict no matter where its version came
    from, so the test would pass against a handler that re-read the
    version after deciding, which is the bug it exists to catch.

    Only against a stream that already has rows, so the genesis append
    this file's fixture makes passes through untouched. A racing store
    that fired on that would conflict during setup and never reach the
    call under test.
    """

    def __init__(self) -> None:
        super().__init__()
        self.raced = False

    async def load(self, stream_type: str, stream_id: UUID) -> tuple[list[StoredEvent], int]:
        rows, version = await super().load(stream_type, stream_id)
        if stream_type == DATASET_STREAM_TYPE and version > 0 and not self.raced:
            self.raced = True
            await super().append(
                stream_type,
                stream_id,
                version,
                [
                    NewEvent(
                        event_id=uuid4(),
                        event_type="DatasetAddressRegistered",
                        schema_version=1,
                        payload={
                            "dataset_id": str(stream_id),
                            "external_ref_scheme": _CENTRAL.scheme,
                            "external_ref_value": _CENTRAL.value,
                            "copied_by_execution_id": None,
                            "copied_by_step_id": None,
                            "occurred_at": _WHEN.isoformat(),
                        },
                        metadata={},
                        correlation_id=uuid4(),
                        causation_id=None,
                        principal_id=uuid4(),
                        occurred_at=_WHEN,
                    )
                ],
            )
        return rows, version


def _kernel(*, authz: object | None = None, event_store: EventStore | None = None) -> Kernel:
    return make_inmemory_kernel(
        settings=Settings(app_env="test"),
        clock=_FixedClock(),
        id_generator=_Uuid4IdGenerator(),
        authz=authz or AllowAllAuthorize(),  # pyright: ignore[reportArgumentType]
        event_store=event_store or InMemoryEventStore(),
    )


async def _a_dataset(deps: Kernel) -> UUID:
    """A dispatched run and one dataset registered against its step."""
    operation_id = await bind_define_operation(deps)(
        DefineOperation(name="count", parameters_schema=_SCHEMA),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )
    procedure_id = await bind_define_procedure(deps)(
        DefineProcedure(
            name="one_scan",
            beamline="2-bm",
            steps=(RunStep(operation_id=operation_id, parameters={}, scopes=("2bmb:det:",)),),
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
    return await bind_register_dataset(deps)(
        RegisterDataset(
            execution_id=execution_id,
            step_id=execution.steps[0].id,
            external_ref=_BEAMLINE,
        ),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )


async def test_a_registered_address_lands_beside_the_one_the_run_wrote() -> None:
    deps = _kernel()
    dataset_id = await _a_dataset(deps)

    await bind_register_address(deps)(
        RegisterDatasetAddress(dataset_id=dataset_id, external_ref=_CENTRAL),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )

    dataset = await load_dataset(deps.event_store, dataset_id)
    assert dataset is not None
    assert dataset.external_refs == (_BEAMLINE, _CENTRAL)


async def test_a_withdrawn_address_leaves_the_rest_of_the_record_alone() -> None:
    deps = _kernel()
    dataset_id = await _a_dataset(deps)
    await bind_register_address(deps)(
        RegisterDatasetAddress(dataset_id=dataset_id, external_ref=_CENTRAL),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )

    await bind_withdraw_address(deps)(
        WithdrawDatasetAddress(dataset_id=dataset_id, external_ref=_BEAMLINE),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )

    dataset = await load_dataset(deps.event_store, dataset_id)
    assert dataset is not None
    assert dataset.external_refs == (_CENTRAL,)


async def test_a_description_lands_with_the_copy_it_was_taken_of() -> None:
    deps = _kernel()
    dataset_id = await _a_dataset(deps)

    await bind_register_manifest(deps)(
        RegisterDatasetManifest(
            dataset_id=dataset_id,
            external_ref=_BEAMLINE,
            manifest=_A_MANIFEST,
            occurred_at=_WHEN,
        ),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )

    dataset = await load_dataset(deps.event_store, dataset_id)
    assert dataset is not None
    assert dataset.description is not None
    assert dataset.description.external_ref == _BEAMLINE
    assert dataset.description.described_at == _WHEN
    assert dataset.description.manifest == _A_MANIFEST
    assert dataset.external_refs == (_BEAMLINE,), "describing moves no data and no address"


async def test_a_denied_description_writes_nothing_to_the_stream() -> None:
    deps = _kernel()
    dataset_id = await _a_dataset(deps)
    before, _version = await deps.event_store.load(DATASET_STREAM_TYPE, dataset_id)
    denied = _kernel(authz=_DenyAllAuthorize(), event_store=deps.event_store)

    with pytest.raises(UnauthorizedError):
        await bind_register_manifest(denied)(
            RegisterDatasetManifest(
                dataset_id=dataset_id, external_ref=_BEAMLINE, manifest=_A_MANIFEST
            ),
            principal_id=uuid4(),
            correlation_id=uuid4(),
        )

    after, _version = await deps.event_store.load(DATASET_STREAM_TYPE, dataset_id)
    assert len(after) == len(before)


async def test_a_finding_lands_on_the_dataset_it_judges() -> None:
    deps = _kernel()
    dataset_id = await _a_dataset(deps)
    reached = Finding(judgement="projections-short-of-plan", expected=128, arrived=100)

    await bind_record_finding(deps)(
        RecordDatasetFinding(dataset_id=dataset_id, finding=reached, occurred_at=_WHEN),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )

    dataset = await load_dataset(deps.event_store, dataset_id)
    assert dataset is not None
    assert dataset.findings == (reached,)
    assert dataset.description is None, "judging opens nothing and describes nothing"
    assert dataset.external_refs == (_BEAMLINE,), "judging moves no data and no address"


async def test_a_denied_finding_writes_nothing_to_the_stream() -> None:
    deps = _kernel()
    dataset_id = await _a_dataset(deps)
    before, _version = await deps.event_store.load(DATASET_STREAM_TYPE, dataset_id)
    denied = _kernel(authz=_DenyAllAuthorize(), event_store=deps.event_store)

    with pytest.raises(UnauthorizedError):
        await bind_record_finding(denied)(
            RecordDatasetFinding(
                dataset_id=dataset_id,
                finding=Finding(judgement="angles-never-recorded", expected=1, arrived=0),
            ),
            principal_id=uuid4(),
            correlation_id=uuid4(),
        )

    after, _version = await deps.event_store.load(DATASET_STREAM_TYPE, dataset_id)
    assert len(after) == len(before)


async def test_a_finding_omitting_its_time_is_stamped_when_the_report_arrived() -> None:
    deps = _kernel()
    dataset_id = await _a_dataset(deps)

    await bind_record_finding(deps)(
        RecordDatasetFinding(
            dataset_id=dataset_id,
            finding=Finding(judgement="angles-never-recorded", expected=1, arrived=0),
        ),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )

    rows, _version = await deps.event_store.load(DATASET_STREAM_TYPE, dataset_id)
    assert rows[-1].occurred_at == _CLOCK_NOW


async def test_a_reported_time_is_what_the_event_carries() -> None:
    deps = _kernel()
    dataset_id = await _a_dataset(deps)

    await bind_register_address(deps)(
        RegisterDatasetAddress(dataset_id=dataset_id, external_ref=_CENTRAL, occurred_at=_WHEN),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )

    rows, _version = await deps.event_store.load(DATASET_STREAM_TYPE, dataset_id)
    assert rows[-1].occurred_at == _WHEN


async def test_omitting_the_time_stamps_the_moment_the_report_arrived() -> None:
    deps = _kernel()
    dataset_id = await _a_dataset(deps)

    await bind_register_address(deps)(
        RegisterDatasetAddress(dataset_id=dataset_id, external_ref=_CENTRAL),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )

    rows, _version = await deps.event_store.load(DATASET_STREAM_TYPE, dataset_id)
    assert rows[-1].occurred_at == _CLOCK_NOW


async def test_a_citation_reaches_the_event_the_handler_appends() -> None:
    deps = _kernel()
    dataset_id = await _a_dataset(deps)
    by_execution, by_step = uuid4(), uuid4()

    await bind_register_address(deps)(
        RegisterDatasetAddress(
            dataset_id=dataset_id,
            external_ref=_CENTRAL,
            copied_by=CopiedBy(execution_id=by_execution, step_id=by_step),
        ),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )

    rows, _version = await deps.event_store.load(DATASET_STREAM_TYPE, dataset_id)
    assert rows[-1].payload["copied_by_execution_id"] == str(by_execution)
    assert rows[-1].payload["copied_by_step_id"] == str(by_step)


async def test_a_denied_caller_writes_nothing_to_the_stream() -> None:
    deps = _kernel()
    dataset_id = await _a_dataset(deps)
    before, _version = await deps.event_store.load(DATASET_STREAM_TYPE, dataset_id)
    denied = _kernel(authz=_DenyAllAuthorize(), event_store=deps.event_store)

    with pytest.raises(UnauthorizedError):
        await bind_register_address(denied)(
            RegisterDatasetAddress(dataset_id=dataset_id, external_ref=_CENTRAL),
            principal_id=uuid4(),
            correlation_id=uuid4(),
        )

    after, _version = await deps.event_store.load(DATASET_STREAM_TYPE, dataset_id)
    assert len(after) == len(before)


async def test_a_denied_withdrawal_writes_nothing_to_the_stream() -> None:
    deps = _kernel()
    dataset_id = await _a_dataset(deps)
    before, _version = await deps.event_store.load(DATASET_STREAM_TYPE, dataset_id)
    denied = _kernel(authz=_DenyAllAuthorize(), event_store=deps.event_store)

    with pytest.raises(UnauthorizedError):
        await bind_withdraw_address(denied)(
            WithdrawDatasetAddress(dataset_id=dataset_id, external_ref=_BEAMLINE),
            principal_id=uuid4(),
            correlation_id=uuid4(),
        )

    after, _version = await deps.event_store.load(DATASET_STREAM_TYPE, dataset_id)
    assert len(after) == len(before)


async def test_an_address_landing_between_the_load_and_the_append_is_refused() -> None:
    """The window the expected version closes.

    Two callers registering an address on one dataset both fold the same
    state and both decide to append at the same version. Passing the
    version the load returned makes the store refuse the second, where a
    blind append would stack on top of the competing event and land the
    duplicate the decider exists to catch.
    """
    store = _RacingEventStore()
    deps = _kernel(event_store=store)
    dataset_id = await _a_dataset(deps)

    with pytest.raises(ConcurrencyError):
        await bind_register_address(deps)(
            RegisterDatasetAddress(dataset_id=dataset_id, external_ref=_CENTRAL),
            principal_id=uuid4(),
            correlation_id=uuid4(),
        )

    assert store.raced, "the racing store never injected a competing write"
    dataset = await load_dataset(store, dataset_id)
    assert dataset is not None
    assert dataset.external_refs == (_BEAMLINE, _CENTRAL), (
        "only the competing write should have landed"
    )
