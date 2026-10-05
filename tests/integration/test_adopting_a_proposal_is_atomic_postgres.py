"""Adoption against a real Postgres, where the all-or-nothing has to be true.

The slice writes three streams across two bounded contexts in one
append, and every other tier takes that on trust: the in-memory store
implements the same port and the same semantics, but it is a dictionary
and a transaction there is not a transaction.

So this is where the property is actually checked. What it is protecting
against is specific. If the procedure, the execution and the adoption
were appended one at a time, a failure after the second would leave a
beamline committed to work that no proposal points at, and the proposal
still reading open for the next caller to adopt and run again.
"""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false

import asyncio
from dataclasses import replace
from typing import TYPE_CHECKING, Any, cast
from uuid import UUID, uuid4

import asyncpg
import pytest

from keeper.counsel.aggregates.proposal import (
    PROPOSAL_STREAM_TYPE,
    ProposalCannotBeAdoptedError,
    ProposalStatus,
    load_proposal,
)
from keeper.counsel.features.adopt_proposal import AdoptProposal
from keeper.counsel.features.adopt_proposal import bind as bind_adopt
from keeper.counsel.features.make_proposal import MakeProposal
from keeper.counsel.features.make_proposal import bind as bind_make
from keeper.execution.aggregates.execution import EXECUTION_STREAM_TYPE, load_execution
from keeper.execution.aggregates.procedure import (
    PROCEDURE_STREAM_TYPE,
    InvalidProcedureStepsError,
    load_procedure,
)
from keeper.execution.features.define_operation import DefineOperation
from keeper.execution.features.define_operation import bind as bind_define_operation
from keeper.infrastructure.deps import make_postgres_kernel
from keeper.infrastructure.kernel import Kernel
from keeper.infrastructure.ports import AllowAllAuthorize
from keeper.infrastructure.ports.clock import SystemClock
from keeper.infrastructure.ports.id_generator import UUIDv7Generator
from keeper.infrastructure.settings import Settings
from tests._racing import HeldAtTheLoad

if TYPE_CHECKING:
    from keeper.infrastructure.ports.event_store import EventStore

pytestmark = [pytest.mark.integration]


@pytest.fixture
def postgres_kernel(db_pool: asyncpg.Pool) -> Kernel:
    """A kernel over the real pool, built the way the application builds one."""
    return make_postgres_kernel(
        db_pool,
        settings=Settings(environment="test"),
        clock=SystemClock(),
        id_generator=UUIDv7Generator(),
        authz=AllowAllAuthorize(),
    )


_SCHEMA: dict[str, Any] = {"$schema": "https://json-schema.org/draft/2020-12/schema"}


async def _a_proposal(deps: Kernel) -> UUID:
    operation_id = await bind_define_operation(deps)(
        DefineOperation(name="count", parameters_schema=_SCHEMA),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )
    return await bind_make(deps)(
        MakeProposal(operation_id=operation_id, parameters={}),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )


async def _stream_count(pool: asyncpg.Pool, stream_type: str) -> int:
    async with pool.acquire() as conn:
        count: int = await conn.fetchval(
            "SELECT count(DISTINCT stream_id) FROM events WHERE stream_type = $1",
            stream_type,
        )
    return count


async def test_adopting_commits_the_procedure_execution_and_proposal_together(
    postgres_kernel: Kernel,
) -> None:
    proposal_id = await _a_proposal(postgres_kernel)

    execution_id = await bind_adopt(postgres_kernel)(
        AdoptProposal(proposal_id=proposal_id, beamline="2-bm", scopes=("2bmb:det:",)),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )

    proposal = await load_proposal(postgres_kernel.event_store, proposal_id)
    execution = await load_execution(postgres_kernel.event_store, execution_id)
    assert execution is not None
    procedure = await load_procedure(postgres_kernel.event_store, execution.procedure_id)
    assert proposal is not None
    assert procedure is not None
    assert proposal.status is ProposalStatus.ADOPTED
    assert proposal.execution_id == execution_id
    assert procedure.beamline.value == "2-bm"


async def test_a_refusal_inside_composing_leaves_no_procedure_and_no_execution(
    postgres_kernel: Kernel, db_pool: asyncpg.Pool
) -> None:
    """The refusal comes from Execution's own decider, after the handler
    has loaded everything and before anything is appended. Nothing may
    survive it on any of the three streams."""
    proposal_id = await _a_proposal(postgres_kernel)
    procedures = await _stream_count(db_pool, PROCEDURE_STREAM_TYPE)
    executions = await _stream_count(db_pool, EXECUTION_STREAM_TYPE)

    with pytest.raises(InvalidProcedureStepsError):
        await bind_adopt(postgres_kernel)(
            AdoptProposal(proposal_id=proposal_id, beamline="2-bm", scopes=()),
            principal_id=uuid4(),
            correlation_id=uuid4(),
        )

    proposal = await load_proposal(postgres_kernel.event_store, proposal_id)
    assert proposal is not None
    assert proposal.status is ProposalStatus.OPEN
    assert await _stream_count(db_pool, PROCEDURE_STREAM_TYPE) == procedures
    assert await _stream_count(db_pool, EXECUTION_STREAM_TYPE) == executions


async def test_a_second_adoption_dispatches_nothing(
    postgres_kernel: Kernel, db_pool: asyncpg.Pool
) -> None:
    """The dangerous direction, and the one the transaction exists for.

    The second call decides a whole procedure and a whole execution
    before the proposal's own decider refuses it. Appended separately,
    those two would already be in the log and a beamline would run the
    same advice twice.
    """
    proposal_id = await _a_proposal(postgres_kernel)
    await bind_adopt(postgres_kernel)(
        AdoptProposal(proposal_id=proposal_id, beamline="2-bm", scopes=("2bmb:det:",)),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )
    procedures = await _stream_count(db_pool, PROCEDURE_STREAM_TYPE)
    executions = await _stream_count(db_pool, EXECUTION_STREAM_TYPE)

    with pytest.raises(ProposalCannotBeAdoptedError):
        await bind_adopt(postgres_kernel)(
            AdoptProposal(proposal_id=proposal_id, beamline="2-bm", scopes=("2bmb:det:",)),
            principal_id=uuid4(),
            correlation_id=uuid4(),
        )

    assert await _stream_count(db_pool, PROCEDURE_STREAM_TYPE) == procedures
    assert await _stream_count(db_pool, EXECUTION_STREAM_TYPE) == executions


async def test_two_callers_adopting_at_once_leave_exactly_one_execution(
    postgres_kernel: Kernel, db_pool: asyncpg.Pool
) -> None:
    """The only failure that happens between the writes rather than before
    them, and therefore the only one that tests the transaction.

    The two refusals above are both decided before anything is appended,
    so separate appends would pass them just as well. This one cannot be
    decided: both callers fold the same open proposal, both decide a
    whole procedure and a whole execution, and the loser only finds out
    when the store rejects its `expected_version`.

    Appended one at a time, that loser has already written a procedure
    and dispatched an execution by the time it is refused, and a
    conductor polling that beamline would walk work no proposal points
    at. In one append it writes nothing at all.

    `HeldAtTheLoad` is what makes that the arrangement rather than the
    hope. Under a bare `asyncio.gather` the first caller reliably
    finished before the second loaded, so the second was refused by the
    decider before it composed anything and the run proved nothing:
    splitting the append into two passed this test on every attempt. The
    barrier holds both callers at the proposal until each has folded it.
    """
    proposal_id = await _a_proposal(postgres_kernel)
    procedures = await _stream_count(db_pool, PROCEDURE_STREAM_TYPE)
    executions = await _stream_count(db_pool, EXECUTION_STREAM_TYPE)
    racing = replace(
        postgres_kernel,
        event_store=cast(
            "EventStore",
            HeldAtTheLoad(postgres_kernel.event_store, asyncio.Barrier(2), on=PROPOSAL_STREAM_TYPE),
        ),
    )
    adopt = bind_adopt(racing)

    async def attempt() -> UUID:
        return await adopt(
            AdoptProposal(proposal_id=proposal_id, beamline="2-bm", scopes=("2bmb:det:",)),
            principal_id=uuid4(),
            correlation_id=uuid4(),
        )

    outcomes = await asyncio.gather(attempt(), attempt(), return_exceptions=True)

    winners = [outcome for outcome in outcomes if isinstance(outcome, UUID)]
    losers = [outcome for outcome in outcomes if isinstance(outcome, BaseException)]
    assert len(winners) == 1, f"exactly one adoption should win, got {outcomes}"
    assert len(losers) == 1, f"exactly one adoption should be refused, got {outcomes}"
    assert await _stream_count(db_pool, PROCEDURE_STREAM_TYPE) == procedures + 1, (
        "the loser decided a procedure and must not have written it"
    )
    assert await _stream_count(db_pool, EXECUTION_STREAM_TYPE) == executions + 1, (
        "the loser dispatched an execution and must not have written it, or a "
        "conductor would walk work no proposal points at"
    )
