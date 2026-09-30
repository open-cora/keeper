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

from keeper.counsel.aggregates.inquiry import (
    INQUIRY_STREAM_TYPE,
    InquiryAnswered,
    InquiryClaimed,
    InquiryMade,
)
from keeper.counsel.aggregates.inquiry import to_payload as inquiry_payload
from keeper.counsel.aggregates.proposal import (
    PROPOSAL_STREAM_TYPE,
    ProposalAdopted,
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
from keeper.execution.aggregates.operation.events import OperationDefined
from keeper.execution.aggregates.operation.events import to_payload as plan_payload
from keeper.execution.aggregates.operation.read import OPERATION_STREAM_TYPE
from keeper.execution.aggregates.operation.state import OperationName
from keeper.execution.aggregates.procedure.events import ProcedureDefined
from keeper.execution.aggregates.procedure.events import to_payload as procedure_payload
from keeper.execution.aggregates.procedure.read import PROCEDURE_STREAM_TYPE
from keeper.execution.aggregates.procedure.state import (
    ComposedStep,
    ProcedureBeamline,
    ProcedureName,
    SetStep,
)
from keeper.infrastructure.ports.event_store import EventStore
from keeper.infrastructure.slices.envelope import to_new_event
from keeper.pursuit.aggregates.pursuit import (
    PURSUIT_STREAM_TYPE,
    PursuitEvent,
    PursuitResumed,
    PursuitRoundClosed,
    PursuitRoundOpened,
    PursuitStarted,
    PursuitWithdrawn,
    RoundOutcome,
)
from keeper.pursuit.aggregates.pursuit import to_payload as pursuit_payload
from keeper.shared.identifier import Identifier

_EMPTY_SCHEMA: Final[dict[str, Any]] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {},
    "required": [],
}
"""The emptiest schema the stored subset will take.

This contract is about finding an operation, not about what one constrains, and
a schema large enough to be interesting would only make the rows harder
to read.
"""


class EventStoreOperationWriter:
    """Writes real operation events, the way the defining handler does.

    The shortest of these writers, because an operation has one event and so
    one verb.
    """

    def __init__(self, event_store: EventStore) -> None:
        self._event_store = event_store
        self._principal_id = uuid4()

    async def define(self, *, operation_id: UUID, name: OperationName, at: datetime) -> None:
        event = OperationDefined(
            operation_id=operation_id,
            operation_name=name.value,
            parameters_schema=dict(_EMPTY_SCHEMA),
            occurred_at=at,
        )
        await self._event_store.append(
            OPERATION_STREAM_TYPE,
            operation_id,
            0,
            [
                to_new_event(
                    event_type=type(event).__name__,
                    payload=plan_payload(event),
                    occurred_at=at,
                    event_id=uuid4(),
                    command_name="DefineOperation",
                    correlation_id=uuid4(),
                    principal_id=self._principal_id,
                )
            ],
        )


class EventStoreDatasetWriter:
    """Writes real dataset events, the way the registering handler does.

    One verb, like the operation writer, because a dataset has one event. It
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
    """Writes real proposal events, the way the three handlers do.

    Three verbs, and two of them close a proposal. Both append at
    version 1, which is what the genesis left behind, so either against
    a proposal that was never made fails here the way it would in the
    application rather than writing an orphan row.

    `make` takes the actor and the operation rather than minting them. The
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
        operation_id: UUID,
        at: datetime,
    ) -> None:
        event = ProposalMade(
            proposal_id=proposal_id,
            actor_id=actor_id,
            operation_id=operation_id,
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

    async def adopt(
        self, *, proposal_id: UUID, execution_id: UUID, step_id: UUID, at: datetime
    ) -> None:
        event = ProposalAdopted(
            proposal_id=proposal_id,
            execution_id=execution_id,
            step_id=step_id,
            occurred_at=at,
        )
        await self._append(proposal_id, 1, event, "AdoptProposal", at)

    async def _append(
        self,
        proposal_id: UUID,
        expected_version: int,
        event: ProposalMade | ProposalTaken | ProposalAdopted,
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


class EventStoreInquiryWriter:
    """Writes real inquiry events, the way the three handlers do.

    Three verbs, and the versions they append at are the point. `claim`
    goes at 1 and `answer` at 1 or 2, because an inquiry may be answered
    without ever being claimed, so the writer counts what it has written
    rather than assuming a shape. A contract that could only build claimed
    inquiries would never exercise the state the read side most easily gets
    wrong.

    `make` takes the asker and the execution rather than minting them, for
    the reason the proposal writer gives: a writer that chose them would
    leave a later check unable to say which inquiries it expected back.
    """

    def __init__(self, event_store: EventStore) -> None:
        self._event_store = event_store
        self._principal_id = uuid4()
        self._versions: dict[UUID, int] = {}

    async def make(
        self,
        *,
        inquiry_id: UUID,
        actor_id: UUID,
        execution_id: UUID,
        objective: str,
        execution_step_count: int,
        at: datetime,
    ) -> None:
        event = InquiryMade(
            inquiry_id=inquiry_id,
            actor_id=actor_id,
            execution_id=execution_id,
            objective=objective,
            execution_step_count=execution_step_count,
            occurred_at=at,
        )
        await self._append(inquiry_id, event, "MakeInquiry", at)

    async def claim(self, *, inquiry_id: UUID, at: datetime) -> None:
        event = InquiryClaimed(inquiry_id=inquiry_id, occurred_at=at)
        await self._append(inquiry_id, event, "ClaimInquiry", at)

    async def answer(
        self,
        *,
        inquiry_id: UUID,
        conclusion: str,
        observed_step_count: int,
        execution_ended: bool,
        proposal_id: UUID | None,
        at: datetime,
    ) -> None:
        event = InquiryAnswered(
            inquiry_id=inquiry_id,
            conclusion=conclusion,
            observed_step_count=observed_step_count,
            execution_ended=execution_ended,
            proposal_id=proposal_id,
            occurred_at=at,
        )
        await self._append(inquiry_id, event, "AnswerInquiry", at)

    async def _append(
        self,
        inquiry_id: UUID,
        event: InquiryMade | InquiryClaimed | InquiryAnswered,
        command_name: str,
        at: datetime,
    ) -> None:
        expected_version = self._versions.get(inquiry_id, 0)
        await self._event_store.append(
            INQUIRY_STREAM_TYPE,
            inquiry_id,
            expected_version,
            [
                to_new_event(
                    event_type=type(event).__name__,
                    payload=inquiry_payload(event),
                    occurred_at=at,
                    event_id=uuid4(),
                    command_name=command_name,
                    correlation_id=uuid4(),
                    principal_id=self._principal_id,
                )
            ],
        )
        self._versions[inquiry_id] = expected_version + 1


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
        beamline: str = "2-bm",
        group: str | None = None,
    ) -> None:
        await self._append(
            device_id,
            DeviceRegistered(
                device_id=device_id,
                external_ref_scheme=external_ref.scheme,
                external_ref_value=external_ref.value,
                device_name=device_name,
                beamline=beamline,
                group=group,
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

    One verb, like the operation writer, because a procedure has one event.

    The steps are moves and nothing else. A summary records how many
    there are and not what they do, so a run would add an operation
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
                ComposedStep(id=uuid4(), step=SetStep(record=f"2bmb:m{i}", to=float(i)))
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
    "EventStoreInquiryWriter",
    "EventStoreOperationWriter",
    "EventStoreProcedureWriter",
    "EventStoreProposalWriter",
    "EventStorePursuitWriter",
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
        step_ids: list[UUID] | None = None,
    ) -> None:
        """Dispatch an execution, optionally with step ids the caller knows.

        `step_ids` exists for the contracts that go on to name a step
        from outside, which a dataset does. Minted here when it is not
        given, because most callers only care that the steps exist.
        """
        chosen = step_ids if step_ids is not None else [uuid4() for _ in steps]
        await self._append(
            execution_id,
            event=ExecutionDispatched(
                execution_id=execution_id,
                procedure_id=procedure_id,
                procedure_name="align_then_scan",
                beamline=beamline,
                steps=[
                    DispatchedStep(id=step_id, describes=text, procedure_step_id=uuid4())
                    for step_id, text in zip(chosen, steps, strict=True)
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

    async def step(
        self,
        *,
        execution_id: UUID,
        index: int,
        at: datetime,
        engine_reference: str | None = None,
    ) -> None:
        """Report one step done, naming the run it opened when it opened one.

        `engine_reference` defaults to nothing, which is a step that
        opened no run. The summary contract does not care either way;
        the step contract is entirely about which steps named one.
        """
        await self._append(
            execution_id,
            event=ExecutionStepDone(
                execution_id=execution_id,
                index=index,
                engine_reference=engine_reference,
                occurred_at=at,
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


class EventStorePursuitWriter:
    """Writes real pursuit events, the way the handlers do.

    Five verbs where the inquiry writer has three, and the reason is the
    same one that made this contract worth its own suite: a pursuit's
    status goes backwards, so a writer that could only build a forward
    sequence would never reach the state the read side most easily gets
    wrong.

    Versions are counted rather than assumed, for the reason they are next
    door. A pursuit may be held, resumed and held again any number of
    times before it is withdrawn, so there is no fixed version any verb
    lands at.

    `start` takes the author, the goal and the beamline rather than
    minting them, because a writer that chose them would leave a later
    check unable to say which pursuits it expected back.

    There is no verb for a charge. Nothing on the summary row moves when
    one lands, and a writer offering one would invite a check on a column
    that does not exist.
    """

    def __init__(self, event_store: EventStore) -> None:
        self._event_store = event_store
        self._principal_id = uuid4()
        self._versions: dict[UUID, int] = {}

    async def start(
        self,
        *,
        pursuit_id: UUID,
        actor_id: UUID,
        goal: str,
        beamline: str,
        at: datetime,
    ) -> None:
        event = PursuitStarted(
            pursuit_id=pursuit_id,
            actor_id=actor_id,
            goal=goal,
            beamline=beamline,
            scopes=("2bmb:det:",),
            budget={"Rounds": 8},
            occurred_at=at,
        )
        await self._append(pursuit_id, event, "StartPursuit", at)

    async def open_round(self, *, pursuit_id: UUID, round_index: int, at: datetime) -> None:
        event = PursuitRoundOpened(
            pursuit_id=pursuit_id,
            round_index=round_index,
            execution_id=uuid4(),
            inquiry_id=uuid4(),
            occurred_at=at,
        )
        await self._append(pursuit_id, event, "OpenPursuitRound", at)

    async def close_round(
        self, *, pursuit_id: UUID, round_index: int, outcome: RoundOutcome, at: datetime
    ) -> None:
        advancing = outcome is RoundOutcome.ADVANCED
        event = PursuitRoundClosed(
            pursuit_id=pursuit_id,
            round_index=round_index,
            outcome=outcome.value,
            proposal_id=uuid4() if advancing else None,
            dispatched_id=uuid4() if advancing else None,
            occurred_at=at,
        )
        await self._append(pursuit_id, event, "ClosePursuitRound", at)

    async def resume(self, *, pursuit_id: UUID, at: datetime) -> None:
        event = PursuitResumed(pursuit_id=pursuit_id, actor_id=uuid4(), occurred_at=at)
        await self._append(pursuit_id, event, "ResumePursuit", at)

    async def withdraw(self, *, pursuit_id: UUID, at: datetime) -> None:
        event = PursuitWithdrawn(pursuit_id=pursuit_id, actor_id=uuid4(), occurred_at=at)
        await self._append(pursuit_id, event, "WithdrawPursuit", at)

    async def _append(
        self,
        pursuit_id: UUID,
        event: PursuitEvent,
        command_name: str,
        at: datetime,
    ) -> None:
        expected_version = self._versions.get(pursuit_id, 0)
        await self._event_store.append(
            PURSUIT_STREAM_TYPE,
            pursuit_id,
            expected_version,
            [
                to_new_event(
                    event_type=type(event).__name__,
                    payload=pursuit_payload(event),
                    occurred_at=at,
                    event_id=uuid4(),
                    command_name=command_name,
                    correlation_id=uuid4(),
                    principal_id=self._principal_id,
                )
            ],
        )
        self._versions[pursuit_id] = expected_version + 1
