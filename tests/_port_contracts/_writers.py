"""Append the events the two summary contracts read back.

Shared by every driver so both sides of each contract are fed the same
rows. Only the reading differs: one driver folds the store the
events went into, the other advances a projection over them first.

Not a check and not a driver, so it sits beside the contracts with a
leading underscore. `test_port_contracts_have_two_sides.py` counts every
module in this package as a contract and every file importing one as a
driver, and a helper counted as a contract would be one nothing drives.
"""

from datetime import datetime
from typing import Any, Final
from uuid import UUID, uuid4

from keeper.counsel.aggregates.proposal import (
    PROPOSAL_STREAM_TYPE,
    ProposalMade,
    ProposalTaken,
)
from keeper.counsel.aggregates.proposal import to_payload as proposal_payload
from keeper.custody.aggregates.dataset.events import DatasetRegistered
from keeper.custody.aggregates.dataset.events import to_payload as dataset_payload
from keeper.custody.aggregates.dataset.read import DATASET_STREAM_TYPE
from keeper.equipment.aggregates.device.events import (
    DeviceEvent,
    DeviceFaulted,
    DeviceRecovered,
    DeviceRegistered,
    DeviceRetired,
)
from keeper.equipment.aggregates.device.events import to_payload as device_payload
from keeper.equipment.aggregates.device.read import DEVICE_STREAM_TYPE
from keeper.execution.aggregates.execution.events import (
    ExecutionClaimed,
    ExecutionDispatched,
    ExecutionEnded,
    ExecutionEvent,
    ExecutionStepDone,
)
from keeper.execution.aggregates.execution.events import to_payload as walk_payload
from keeper.execution.aggregates.execution.read import EXECUTION_STREAM_TYPE
from keeper.execution.aggregates.execution.state import DispatchedStep
from keeper.execution.aggregates.plan.events import PlanDefined
from keeper.execution.aggregates.plan.events import to_payload as plan_payload
from keeper.execution.aggregates.plan.read import PLAN_STREAM_TYPE
from keeper.execution.aggregates.plan.state import PlanName
from keeper.execution.aggregates.procedure.events import ProcedureDefined
from keeper.execution.aggregates.procedure.events import to_payload as procedure_payload
from keeper.execution.aggregates.procedure.read import PROCEDURE_STREAM_TYPE
from keeper.execution.aggregates.procedure.state import (
    ComposedStep,
    MoveStep,
    ProcedureBeamline,
    ProcedureName,
)
from keeper.infrastructure.ports.event_store import EventStore
from keeper.infrastructure.slices.envelope import to_new_event
from keeper.shared.identifier import Identifier

_EMPTY_SCHEMA: Final[dict[str, Any]] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {},
    "required": [],
}
"""The emptiest schema the stored subset will take.

This contract is about finding a plan, not about what one constrains, and
a schema large enough to be interesting would only make the rows harder
to read.
"""


class EventStorePlanWriter:
    """Writes real plan events, the way the defining handler does.

    The shortest of these writers, because a plan has one event and so
    one verb.
    """

    def __init__(self, event_store: EventStore) -> None:
        self._event_store = event_store
        self._principal_id = uuid4()

    async def define(self, *, plan_id: UUID, name: PlanName, at: datetime) -> None:
        event = PlanDefined(
            plan_id=plan_id,
            plan_name=name.value,
            parameters_schema=dict(_EMPTY_SCHEMA),
            occurred_at=at,
        )
        await self._event_store.append(
            PLAN_STREAM_TYPE,
            plan_id,
            0,
            [
                to_new_event(
                    event_type=type(event).__name__,
                    payload=plan_payload(event),
                    occurred_at=at,
                    event_id=uuid4(),
                    command_name="DefinePlan",
                    correlation_id=uuid4(),
                    principal_id=self._principal_id,
                )
            ],
        )


class EventStoreDatasetWriter:
    """Writes real dataset events, the way the registering handler does.

    One verb, like the plan writer, because a dataset has one event. It
    takes the execution and step ids rather than minting them, because the step is the
    thing the contract's filter selects on and a writer choosing it would
    leave every check unable to say which datasets it expected back.
    """

    def __init__(self, event_store: EventStore) -> None:
        self._event_store = event_store
        self._principal_id = uuid4()

    async def register(
        self,
        *,
        dataset_id: UUID,
        execution_id: UUID,
        step_id: UUID,
        external_ref: Identifier,
        at: datetime,
    ) -> None:
        event = DatasetRegistered(
            dataset_id=dataset_id,
            execution_id=execution_id,
            step_id=step_id,
            external_ref_scheme=external_ref.scheme,
            external_ref_value=external_ref.value,
            occurred_at=at,
        )
        await self._event_store.append(
            DATASET_STREAM_TYPE,
            dataset_id,
            0,
            [
                to_new_event(
                    event_type=type(event).__name__,
                    payload=dataset_payload(event),
                    occurred_at=at,
                    event_id=uuid4(),
                    command_name="RegisterDataset",
                    correlation_id=uuid4(),
                    principal_id=self._principal_id,
                )
            ],
        )


class EventStoreProposalWriter:
    """Writes real proposal events, the way the two handlers do.

    Two verbs, unlike the three writers above, because this is the first
    aggregate a contract suite drives that has a second event. `take`
    appends at version 1, which is what the genesis left behind, so a
    take against a proposal that was never made fails here the way it
    would in the application rather than writing an orphan row.

    `make` takes the actor and the plan rather than minting them. The
    contract does not filter on either today, and a writer that chose
    them would leave a later check unable to say which proposals it
    expected back.
    """

    def __init__(self, event_store: EventStore) -> None:
        self._event_store = event_store
        self._principal_id = uuid4()

    async def make(
        self,
        *,
        proposal_id: UUID,
        actor_id: UUID,
        plan_id: UUID,
        at: datetime,
    ) -> None:
        event = ProposalMade(
            proposal_id=proposal_id,
            actor_id=actor_id,
            plan_id=plan_id,
            parameters={},
            occurred_at=at,
        )
        await self._append(proposal_id, 0, event, "MakeProposal", at)

    async def take(
        self, *, proposal_id: UUID, execution_id: UUID, step_id: UUID, at: datetime
    ) -> None:
        event = ProposalTaken(
            proposal_id=proposal_id,
            execution_id=execution_id,
            step_id=step_id,
            occurred_at=at,
        )
        await self._append(proposal_id, 1, event, "TakeProposal", at)

    async def _append(
        self,
        proposal_id: UUID,
        expected_version: int,
        event: ProposalMade | ProposalTaken,
        command_name: str,
        at: datetime,
    ) -> None:
        await self._event_store.append(
            PROPOSAL_STREAM_TYPE,
            proposal_id,
            expected_version,
            [
                to_new_event(
                    event_type=type(event).__name__,
                    payload=proposal_payload(event),
                    occurred_at=at,
                    event_id=uuid4(),
                    command_name=command_name,
                    correlation_id=uuid4(),
                    principal_id=self._principal_id,
                )
            ],
        )


class EventStoreDeviceWriter:
    """Writes real device events, the way the four handlers do.

    Four verbs, which is the most of any writer here, because this is
    the first aggregate a contract suite drives whose state machine has
    more than one edge. The three transitions all take the version they
    expect, so a recovery against a device that was never registered
    fails here the way it would in the application rather than writing
    an orphan row.

    Version is tracked per device rather than passed in, because a
    contract check moving one device through two transitions should read
    as a sequence of acts and not as arithmetic on a stream version.
    """

    def __init__(self, event_store: EventStore) -> None:
        self._event_store = event_store
        self._principal_id = uuid4()
        self._versions: dict[UUID, int] = {}

    async def register(
        self,
        *,
        device_id: UUID,
        external_ref: Identifier,
        device_name: str,
        at: datetime,
    ) -> None:
        await self._append(
            device_id,
            DeviceRegistered(
                device_id=device_id,
                external_ref_scheme=external_ref.scheme,
                external_ref_value=external_ref.value,
                device_name=device_name,
                occurred_at=at,
            ),
            "RegisterDevice",
            at,
        )

    async def fault(self, *, device_id: UUID, at: datetime) -> None:
        await self._append(
            device_id, DeviceFaulted(device_id=device_id, occurred_at=at), "FaultDevice", at
        )

    async def recover(self, *, device_id: UUID, at: datetime) -> None:
        await self._append(
            device_id, DeviceRecovered(device_id=device_id, occurred_at=at), "RecoverDevice", at
        )

    async def retire(self, *, device_id: UUID, at: datetime) -> None:
        await self._append(
            device_id, DeviceRetired(device_id=device_id, occurred_at=at), "RetireDevice", at
        )

    async def _append(
        self,
        device_id: UUID,
        event: DeviceEvent,
        command_name: str,
        at: datetime,
    ) -> None:
        version = self._versions.get(device_id, 0)
        await self._event_store.append(
            DEVICE_STREAM_TYPE,
            device_id,
            version,
            [
                to_new_event(
                    event_type=type(event).__name__,
                    payload=device_payload(event),
                    occurred_at=at,
                    event_id=uuid4(),
                    command_name=command_name,
                    correlation_id=uuid4(),
                    principal_id=self._principal_id,
                )
            ],
        )
        self._versions[device_id] = version + 1


class EventStoreProcedureWriter:
    """Writes real procedure events, the way the defining handler does.

    One verb, like the plan writer, because a procedure has one event.

    The steps are moves and nothing else. A summary records how many
    there are and not what they do, so an acquisition would add a plan
    stream this writer would then have to create for the parameters check
    it is not exercising.
    """

    def __init__(self, event_store: EventStore) -> None:
        self._event_store = event_store
        self._principal_id = uuid4()

    async def define(
        self,
        *,
        procedure_id: UUID,
        name: ProcedureName,
        steps: int,
        at: datetime,
        beamline: str = "2-bm",
    ) -> None:
        event = ProcedureDefined(
            procedure_id=procedure_id,
            procedure_name=name.value,
            beamline=ProcedureBeamline(beamline).value,
            steps=tuple(
                ComposedStep(id=uuid4(), step=MoveStep(record=f"2bmb:m{i}", to=float(i)))
                for i in range(steps)
            ),
            occurred_at=at,
        )
        await self._event_store.append(
            PROCEDURE_STREAM_TYPE,
            procedure_id,
            0,
            [
                to_new_event(
                    event_type=type(event).__name__,
                    payload=procedure_payload(event),
                    occurred_at=at,
                    event_id=uuid4(),
                    command_name="DefineProcedure",
                    correlation_id=uuid4(),
                    principal_id=self._principal_id,
                )
            ],
        )


__all__ = [
    "EventStoreDatasetWriter",
    "EventStoreDeviceWriter",
    "EventStorePlanWriter",
    "EventStoreProcedureWriter",
    "EventStoreProposalWriter",
]


class EventStoreExecutionWriter:
    """Writes real execution events, the way the four handlers do.

    Four verbs, because four are enough to reach every column: the
    genesis sets the procedure and the step count, a claim and a step
    each move the status, and an ending moves it to its terminal. Which
    of the four step events is used does not matter to a summary, which
    records that a step was reported and not how it ended, so the done
    one stands for all of them.

    The version is tracked here rather than passed in, because an execution
    takes any number of steps and a caller counting appends would be
    keeping the store's bookkeeping on its behalf.
    """

    def __init__(self, event_store: EventStore) -> None:
        self._event_store = event_store
        self._principal_id = uuid4()
        self._versions: dict[UUID, int] = {}

    async def dispatch(
        self,
        *,
        execution_id: UUID,
        procedure_id: UUID,
        steps: list[str],
        at: datetime,
        beamline: str = "2-bm",
    ) -> None:
        await self._append(
            execution_id,
            event=ExecutionDispatched(
                execution_id=execution_id,
                procedure_id=procedure_id,
                procedure_name="align_then_scan",
                beamline=beamline,
                steps=[
                    DispatchedStep(id=uuid4(), describes=text, procedure_step_id=uuid4())
                    for text in steps
                ],
                occurred_at=at,
            ),
            command_name="DispatchExecution",
        )

    async def claim(self, *, execution_id: UUID, at: datetime) -> None:
        await self._append(
            execution_id,
            event=ExecutionClaimed(execution_id=execution_id, occurred_at=at),
            command_name="ClaimExecution",
        )

    async def step(self, *, execution_id: UUID, index: int, at: datetime) -> None:
        await self._append(
            execution_id,
            event=ExecutionStepDone(
                execution_id=execution_id, index=index, engine_reference=None, occurred_at=at
            ),
            command_name="ReportExecutionStep",
        )

    async def end(self, *, execution_id: UUID, at: datetime) -> None:
        await self._append(
            execution_id,
            event=ExecutionEnded(execution_id=execution_id, occurred_at=at),
            command_name="EndExecution",
        )

    async def _append(
        self,
        execution_id: UUID,
        *,
        event: ExecutionEvent,
        command_name: str,
    ) -> None:
        version = self._versions.get(execution_id, 0)
        await self._event_store.append(
            EXECUTION_STREAM_TYPE,
            execution_id,
            version,
            [
                to_new_event(
                    event_type=type(event).__name__,
                    payload=walk_payload(event),
                    occurred_at=event.occurred_at,
                    event_id=uuid4(),
                    command_name=command_name,
                    correlation_id=uuid4(),
                    principal_id=self._principal_id,
                )
            ],
        )
        self._versions[execution_id] = version + 1
