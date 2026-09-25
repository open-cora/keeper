"""The three Counsel handlers, against in-process stores.

One file for three handlers, because what is worth testing about them is
shared: each reads across into Execution, and the cases that matter are
the ones about that read and about who the record says proposed.

The split between this file and the two decider files is the usual one.
A decider is handed its inputs; a handler is what fetches them, refuses
a sibling that is not there, and picks which moment to stamp.
"""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest

from keeper.counsel.aggregates.proposal import (
    PROPOSAL_STREAM_TYPE,
    ProposalCannotBeTakenError,
    ProposalNotFoundError,
    load_proposal,
)
from keeper.counsel.errors import UnauthorizedError
from keeper.counsel.features.get_proposal import GetProposal
from keeper.counsel.features.get_proposal import bind as bind_get
from keeper.counsel.features.make_proposal import MakeProposal
from keeper.counsel.features.make_proposal import bind as bind_make
from keeper.counsel.features.take_proposal import TakeProposal
from keeper.counsel.features.take_proposal import bind as bind_take
from keeper.execution.aggregates.execution import (
    ExecutionNotFoundError,
    ExecutionStepNotFoundError,
    load_execution,
)
from keeper.execution.aggregates.plan import PlanNotFoundError
from keeper.execution.aggregates.procedure import AcquireStep, MoveStep
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
from keeper.shared.reserved_ids import NIL_SENTINEL_ID

pytestmark = pytest.mark.unit

_CLOCK_NOW = datetime(2026, 9, 19, 9, 0, tzinfo=UTC)
"""What the clock says, deliberately not the time any caller reports."""
_REPORTED = datetime(2026, 9, 18, 6, 0, tzinfo=UTC)
_SCHEMA: dict[str, Any] = {"$schema": "https://json-schema.org/draft/2020-12/schema"}
_PARAMETERS: dict[str, Any] = {"exposure_time_s": 0.1}


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


async def _a_plan(deps: Kernel) -> UUID:
    return await bind_define_plan(deps)(
        DefinePlan(name="count", parameters_schema=_SCHEMA),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )


async def _an_acquisition_of(deps: Kernel, plan_id: UUID) -> tuple[UUID, UUID]:
    """Compose a procedure that acquires with this plan, dispatch it, hand back both ids.

    The whole chain has to be real, because the taking handler checks
    that the execution holds the step: a step is an entity inside that
    aggregate rather than a stream of its own, so there is nothing to
    fake short of dispatching something.

    A move goes in front of the acquisition so the step this returns is
    never the first one. A procedure of one acquisition would let an
    off-by-one in the search pass.
    """
    procedure_id = await bind_define_procedure(deps)(
        DefineProcedure(
            name="align_then_scan",
            beamline="2-bm",
            steps=(
                MoveStep(record="2bmb:m1", to=0.0),
                AcquireStep(plan_id=plan_id, parameters=dict(_PARAMETERS), scopes=("2bmb:det:",)),
            ),
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
    return execution_id, execution.steps[1].id


async def _a_move_in(deps: Kernel) -> tuple[UUID, UUID]:
    """A dispatched step that runs no plan, for the refusal that needs one."""
    procedure_id = await bind_define_procedure(deps)(
        DefineProcedure(name="park", beamline="2-bm", steps=(MoveStep(record="2bmb:m1", to=0.0),)),
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


async def test_making_a_proposal_writes_one_event_and_returns_its_id() -> None:
    deps = _kernel()
    plan_id = await _a_plan(deps)

    proposal_id = await bind_make(deps)(
        MakeProposal(plan_id=plan_id, parameters=dict(_PARAMETERS)),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )

    stored, _version = await deps.event_store.load(PROPOSAL_STREAM_TYPE, proposal_id)
    assert [row.event_type for row in stored] == ["ProposalMade"]


async def test_the_principal_becomes_the_proposer_on_the_record() -> None:
    """The one place this handler does more than plumb."""
    deps = _kernel()
    plan_id = await _a_plan(deps)
    principal_id = uuid4()

    proposal_id = await bind_make(deps)(
        MakeProposal(plan_id=plan_id, parameters={}),
        principal_id=principal_id,
        correlation_id=uuid4(),
    )

    proposal = await load_proposal(deps.event_store, proposal_id)
    assert proposal is not None
    assert proposal.actor_id == principal_id


async def test_a_proposal_is_stamped_with_the_clock_and_nothing_else() -> None:
    """R8 in the wiring: there is no reported time for a caller to send."""
    deps = _kernel()
    plan_id = await _a_plan(deps)

    proposal_id = await bind_make(deps)(
        MakeProposal(plan_id=plan_id, parameters={}),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )

    stored, _version = await deps.event_store.load(PROPOSAL_STREAM_TYPE, proposal_id)
    assert stored[0].occurred_at == _CLOCK_NOW


async def test_proposing_against_a_plan_that_is_not_there_is_refused() -> None:
    deps = _kernel()

    with pytest.raises(PlanNotFoundError):
        await bind_make(deps)(
            MakeProposal(plan_id=uuid4(), parameters={}),
            principal_id=uuid4(),
            correlation_id=uuid4(),
        )


async def test_a_denied_caller_makes_no_proposal() -> None:
    deps = _kernel(authz=_DenyAllAuthorize())
    plan_id = await _a_plan(_kernel())

    with pytest.raises(UnauthorizedError):
        await bind_make(deps)(
            MakeProposal(plan_id=plan_id, parameters={}),
            principal_id=uuid4(),
            correlation_id=uuid4(),
        )


async def test_taking_a_proposal_appends_to_the_stream_the_genesis_opened() -> None:
    deps = _kernel()
    plan_id = await _a_plan(deps)
    execution_id, step_id = await _an_acquisition_of(deps, plan_id)
    proposal_id = await bind_make(deps)(
        MakeProposal(plan_id=plan_id, parameters=dict(_PARAMETERS)),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )

    await bind_take(deps)(
        TakeProposal(proposal_id=proposal_id, execution_id=execution_id, step_id=step_id),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )

    stored, _version = await deps.event_store.load(PROPOSAL_STREAM_TYPE, proposal_id)
    assert [row.event_type for row in stored] == ["ProposalMade", "ProposalTaken"]


async def test_a_taken_proposal_reads_back_with_its_acquisition_recorded() -> None:
    deps = _kernel()
    plan_id = await _a_plan(deps)
    execution_id, step_id = await _an_acquisition_of(deps, plan_id)
    proposal_id = await bind_make(deps)(
        MakeProposal(plan_id=plan_id, parameters={}),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )

    await bind_take(deps)(
        TakeProposal(proposal_id=proposal_id, execution_id=execution_id, step_id=step_id),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )

    proposal = await load_proposal(deps.event_store, proposal_id)
    assert proposal is not None
    assert (proposal.execution_id, proposal.step_id) == (execution_id, step_id)


async def test_a_reported_time_beats_the_clock_when_a_take_carries_one() -> None:
    deps = _kernel()
    plan_id = await _a_plan(deps)
    execution_id, step_id = await _an_acquisition_of(deps, plan_id)
    proposal_id = await bind_make(deps)(
        MakeProposal(plan_id=plan_id, parameters={}),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )

    await bind_take(deps)(
        TakeProposal(
            proposal_id=proposal_id,
            execution_id=execution_id,
            step_id=step_id,
            occurred_at=_REPORTED,
        ),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )

    stored, _version = await deps.event_store.load(PROPOSAL_STREAM_TYPE, proposal_id)
    assert (stored[0].occurred_at, stored[1].occurred_at) == (_CLOCK_NOW, _REPORTED)


async def test_taking_with_an_execution_that_is_not_there_is_the_handlers_refusal() -> None:
    deps = _kernel()
    plan_id = await _a_plan(deps)
    proposal_id = await bind_make(deps)(
        MakeProposal(plan_id=plan_id, parameters={}),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )

    with pytest.raises(ExecutionNotFoundError):
        await bind_take(deps)(
            TakeProposal(proposal_id=proposal_id, execution_id=uuid4(), step_id=uuid4()),
            principal_id=uuid4(),
            correlation_id=uuid4(),
        )

    stored, _version = await deps.event_store.load(PROPOSAL_STREAM_TYPE, proposal_id)
    assert len(stored) == 1


async def test_taking_with_a_step_that_execution_does_not_hold_is_refused() -> None:
    """The second of the two checks a step reference costs.

    The execution is there and the step is not, which is the case a
    single existence check would let through: the caller has resolved a
    real traversal and named something inside it that is not there.
    """
    deps = _kernel()
    plan_id = await _a_plan(deps)
    execution_id, _step_id = await _an_acquisition_of(deps, plan_id)
    proposal_id = await bind_make(deps)(
        MakeProposal(plan_id=plan_id, parameters={}),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )

    with pytest.raises(ExecutionStepNotFoundError):
        await bind_take(deps)(
            TakeProposal(proposal_id=proposal_id, execution_id=execution_id, step_id=uuid4()),
            principal_id=uuid4(),
            correlation_id=uuid4(),
        )

    stored, _version = await deps.event_store.load(PROPOSAL_STREAM_TYPE, proposal_id)
    assert len(stored) == 1


async def test_taking_with_an_acquisition_of_another_plan_writes_nothing() -> None:
    deps = _kernel()
    proposed_plan = await _a_plan(deps)
    other_plan = await _a_plan(deps)
    other_execution, other_step = await _an_acquisition_of(deps, other_plan)
    proposal_id = await bind_make(deps)(
        MakeProposal(plan_id=proposed_plan, parameters={}),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )

    with pytest.raises(ProposalCannotBeTakenError):
        await bind_take(deps)(
            TakeProposal(proposal_id=proposal_id, execution_id=other_execution, step_id=other_step),
            principal_id=uuid4(),
            correlation_id=uuid4(),
        )

    stored, _version = await deps.event_store.load(PROPOSAL_STREAM_TYPE, proposal_id)
    assert len(stored) == 1


async def test_a_move_cannot_take_a_proposal_even_though_the_step_is_real() -> None:
    """The refusal that only exists because a step can be something else.

    A run was always a run. A step is a move or an acquisition, so the
    handler can resolve a step that exists, belongs to a real execution,
    and still cannot have run what was proposed.
    """
    deps = _kernel()
    plan_id = await _a_plan(deps)
    execution_id, step_id = await _a_move_in(deps)
    proposal_id = await bind_make(deps)(
        MakeProposal(plan_id=plan_id, parameters={}),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )

    with pytest.raises(ProposalCannotBeTakenError, match="runs no plan"):
        await bind_take(deps)(
            TakeProposal(proposal_id=proposal_id, execution_id=execution_id, step_id=step_id),
            principal_id=uuid4(),
            correlation_id=uuid4(),
        )

    stored, _version = await deps.event_store.load(PROPOSAL_STREAM_TYPE, proposal_id)
    assert len(stored) == 1


async def test_reading_a_proposal_that_was_never_made_is_refused() -> None:
    deps = _kernel()

    with pytest.raises(ProposalNotFoundError):
        await bind_get(deps)(
            GetProposal(proposal_id=uuid4()),
            principal_id=uuid4(),
            correlation_id=uuid4(),
        )


async def test_reading_one_back_gives_what_was_proposed() -> None:
    deps = _kernel()
    plan_id = await _a_plan(deps)
    principal_id = uuid4()
    proposal_id = await bind_make(deps)(
        MakeProposal(plan_id=plan_id, parameters=dict(_PARAMETERS)),
        principal_id=principal_id,
        correlation_id=uuid4(),
    )

    proposal = await bind_get(deps)(
        GetProposal(proposal_id=proposal_id),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )

    assert (proposal.id, proposal.actor_id, proposal.plan_id) == (
        proposal_id,
        principal_id,
        plan_id,
    )
    assert proposal.parameters == _PARAMETERS
    assert (proposal.execution_id, proposal.step_id) == (None, None)


async def test_a_denied_caller_cannot_read_a_proposal() -> None:
    deps = _kernel(authz=_DenyAllAuthorize())

    with pytest.raises(UnauthorizedError):
        await bind_get(deps)(
            GetProposal(proposal_id=uuid4()),
            principal_id=uuid4(),
            correlation_id=uuid4(),
        )
