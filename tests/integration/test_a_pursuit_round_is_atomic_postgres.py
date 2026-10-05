"""Opening a round against a real Postgres, where the all-or-nothing has to be true.

The slice writes two streams across two bounded contexts in one append,
and every other tier takes that on trust: the in-memory store implements
the same port and the same semantics, but it is a dictionary and a
transaction there is not a transaction.

So this is where the property is actually checked, and what it protects
against is specific to this slice. The round is what the budget counts and
what refuses a repeat. If the two were appended one at a time and the
second failed, the pursuit would hold a round citing a question that does
not exist: the budget already spent, and the caller retrying refused by
the round its own failure left behind. That pursuit could never ask about
that execution again, and nothing short of a person reading the log would
say why.

The race below is the test that earns its place. Both refusals in this
slice are decided before anything is appended, so every arrangement that
only checks a refusal passes just as well against two separate appends. It
takes two callers that have both already read the pursuit to tell the two
apart.

Getting them there is not something `asyncio.gather` can be trusted to do.
Two coroutines over one pool may interleave at their awaits or may not,
and a first draft of the race below ran entirely serially: the second
caller loaded a pursuit that already held the round, was refused before it
appended anything, and the two-appends mutation went green. So the store
is wrapped in a barrier that holds both callers at the load. What is
tested is the same property, and it is now tested every run rather than on
the runs where the scheduler cooperated.
"""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false

import asyncio
from dataclasses import replace
from typing import TYPE_CHECKING, Any, cast
from uuid import UUID, uuid4

import asyncpg
import pytest

from keeper.counsel.aggregates.inquiry import (
    INQUIRY_STREAM_TYPE,
    InquiryConclusion,
    load_inquiry,
)
from keeper.counsel.aggregates.proposal import (
    ProposalCannotBeAdoptedError,
    ProposalStatus,
    load_proposal,
)
from keeper.counsel.features.adopt_proposal import AdoptProposal
from keeper.counsel.features.adopt_proposal import bind as bind_adopt
from keeper.counsel.features.answer_inquiry import AnswerInquiry
from keeper.counsel.features.answer_inquiry import bind as bind_answer
from keeper.counsel.features.make_proposal import MakeProposal
from keeper.counsel.features.make_proposal import bind as bind_make_proposal
from keeper.execution.aggregates.execution import (
    EXECUTION_STREAM_TYPE,
    ExecutionNotFoundError,
    load_execution,
)
from keeper.execution.aggregates.procedure import PROCEDURE_STREAM_TYPE, SetStep, load_procedure
from keeper.execution.features.define_operation import DefineOperation
from keeper.execution.features.define_operation import bind as bind_define_operation
from keeper.execution.features.define_procedure import DefineProcedure
from keeper.execution.features.define_procedure import bind as bind_define_procedure
from keeper.execution.features.dispatch_execution import DispatchExecution
from keeper.execution.features.dispatch_execution import bind as bind_dispatch
from keeper.infrastructure.deps import make_postgres_kernel
from keeper.infrastructure.kernel import Kernel
from keeper.infrastructure.ports import AllowAllAuthorize
from keeper.infrastructure.ports.clock import SystemClock
from keeper.infrastructure.ports.id_generator import UUIDv7Generator
from keeper.infrastructure.settings import Settings
from keeper.pursuit.aggregates.pursuit import (
    PURSUIT_STREAM_TYPE,
    Budget,
    BudgetDimension,
    PursuitBeamline,
    PursuitGoal,
    load_pursuit,
)
from keeper.pursuit.features.close_pursuit_round import ClosePursuitRound
from keeper.pursuit.features.close_pursuit_round import bind as bind_close
from keeper.pursuit.features.open_pursuit_round import OpenPursuitRound
from keeper.pursuit.features.open_pursuit_round import bind as bind_open_round
from keeper.pursuit.features.start_pursuit import StartPursuit
from keeper.pursuit.features.start_pursuit import bind as bind_start

if TYPE_CHECKING:
    from keeper.infrastructure.ports.event_store import EventStore

from tests._racing import HeldAtTheLoad

pytestmark = [pytest.mark.integration]

_SCHEMA: dict[str, Any] = {"$schema": "https://json-schema.org/draft/2020-12/schema"}


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


async def _a_pursuit(deps: Kernel, *, rounds: int = 8) -> UUID:
    return await bind_start(deps)(
        StartPursuit(
            goal=PursuitGoal("find the edge of the useful exposure range"),
            beamline=PursuitBeamline("2-bm"),
            scopes=("2bmb:m1",),
            budget=Budget({BudgetDimension.ROUNDS: rounds}),
        ),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )


async def _an_execution(deps: Kernel) -> UUID:
    procedure_id = await bind_define_procedure(deps)(
        DefineProcedure(name="park", beamline="2-bm", steps=(SetStep(record="2bmb:m1", to=0.0),)),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )
    return await bind_dispatch(deps)(
        DispatchExecution(procedure_id=procedure_id),
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


async def test_opening_a_round_commits_the_pursuit_and_the_inquiry_together(
    postgres_kernel: Kernel,
) -> None:
    pursuit_id = await _a_pursuit(postgres_kernel)
    execution_id = await _an_execution(postgres_kernel)

    inquiry_id = await bind_open_round(postgres_kernel)(
        OpenPursuitRound(pursuit_id=pursuit_id, execution_id=execution_id),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )

    pursuit = await load_pursuit(postgres_kernel.event_store, pursuit_id)
    inquiry = await load_inquiry(postgres_kernel.event_store, inquiry_id)
    assert pursuit is not None
    assert inquiry is not None
    assert pursuit.rounds[0].inquiry_id == inquiry_id
    assert inquiry.execution_id == execution_id


async def test_a_round_naming_no_execution_leaves_no_inquiry_behind(
    postgres_kernel: Kernel, db_pool: asyncpg.Pool
) -> None:
    """The inquiry is a genesis on a fresh stream, so nothing in Counsel
    would refuse it. What stops it is the load this handler does first, and
    what this checks is that the refusal reached the store as nothing."""
    pursuit_id = await _a_pursuit(postgres_kernel)
    before = await _stream_count(db_pool, INQUIRY_STREAM_TYPE)

    with pytest.raises(ExecutionNotFoundError):
        await bind_open_round(postgres_kernel)(
            OpenPursuitRound(pursuit_id=pursuit_id, execution_id=uuid4()),
            principal_id=uuid4(),
            correlation_id=uuid4(),
        )

    assert await _stream_count(db_pool, INQUIRY_STREAM_TYPE) == before
    pursuit = await load_pursuit(postgres_kernel.event_store, pursuit_id)
    assert pursuit is not None
    assert pursuit.rounds == ()


async def test_two_callers_opening_one_round_at_once_leave_exactly_one(
    postgres_kernel: Kernel, db_pool: asyncpg.Pool
) -> None:
    """The test that tells one append from two.

    Both callers fold the same pursuit, both decide a round, both decide an
    inquiry, and both append at the same expected version. The store lets
    one through. What the loser must not have left behind is its inquiry:
    that append was a genesis on a stream nothing else touches, so nothing
    but the transaction can refuse it.

    Replace the single `append_streams` with two appends and this is the
    arrangement that notices, because the loser's inquiry lands before its
    pursuit append is rejected.
    """
    pursuit_id = await _a_pursuit(postgres_kernel)
    execution_id = await _an_execution(postgres_kernel)
    before = await _stream_count(db_pool, INQUIRY_STREAM_TYPE)
    racing = replace(
        postgres_kernel,
        event_store=cast(
            "EventStore",
            HeldAtTheLoad(postgres_kernel.event_store, asyncio.Barrier(2), on=PURSUIT_STREAM_TYPE),
        ),
    )
    open_round = bind_open_round(racing)

    async def open_one() -> object:
        return await open_round(
            OpenPursuitRound(pursuit_id=pursuit_id, execution_id=execution_id),
            principal_id=uuid4(),
            correlation_id=uuid4(),
        )

    outcomes = await asyncio.gather(open_one(), open_one(), return_exceptions=True)

    won = [outcome for outcome in outcomes if isinstance(outcome, UUID)]
    assert len(won) == 1, f"exactly one caller may open the round, got {outcomes}"
    pursuit = await load_pursuit(postgres_kernel.event_store, pursuit_id)
    assert pursuit is not None
    assert len(pursuit.rounds) == 1
    assert await _stream_count(db_pool, INQUIRY_STREAM_TYPE) == before + 1, (
        "the loser decided an inquiry and must not have written it"
    )


async def test_a_round_past_the_budget_writes_neither_stream(
    postgres_kernel: Kernel, db_pool: asyncpg.Pool
) -> None:
    pursuit_id = await _a_pursuit(postgres_kernel, rounds=1)
    await bind_open_round(postgres_kernel)(
        OpenPursuitRound(pursuit_id=pursuit_id, execution_id=await _an_execution(postgres_kernel)),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )
    after_one = await _stream_count(db_pool, INQUIRY_STREAM_TYPE)

    with pytest.raises(Exception, match="Rounds"):
        await bind_open_round(postgres_kernel)(
            OpenPursuitRound(
                pursuit_id=pursuit_id, execution_id=await _an_execution(postgres_kernel)
            ),
            principal_id=uuid4(),
            correlation_id=uuid4(),
        )

    assert await _stream_count(db_pool, INQUIRY_STREAM_TYPE) == after_one
    pursuit = await load_pursuit(postgres_kernel.event_store, pursuit_id)
    assert pursuit is not None
    assert len(pursuit.rounds) == 1


async def _a_proposal(deps: Kernel) -> UUID:
    operation_id = await bind_define_operation(deps)(
        DefineOperation(name="count", parameters_schema=_SCHEMA),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )
    return await bind_make_proposal(deps)(
        MakeProposal(operation_id=operation_id, parameters={}),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )


async def _answered_with_a_proposal(deps: Kernel, inquiry_id: UUID, proposal_id: UUID) -> None:
    await bind_answer(deps)(
        AnswerInquiry(
            inquiry_id=inquiry_id,
            conclusion=InquiryConclusion.PROPOSE,
            observed_step_count=1,
            execution_ended=True,
            proposal_id=proposal_id,
        ),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )


async def test_closing_on_a_proposal_commits_four_streams_across_three_contexts(
    postgres_kernel: Kernel,
) -> None:
    """The widest write in this tree, and the only place it is real.

    A procedure, an execution, the proposal being adopted and the round
    advancing. Three bounded contexts, one transaction, and nothing in the
    closing call names a beamline.
    """
    pursuit_id = await _a_pursuit(postgres_kernel)
    inquiry_id = await bind_open_round(postgres_kernel)(
        OpenPursuitRound(pursuit_id=pursuit_id, execution_id=await _an_execution(postgres_kernel)),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )
    proposal_id = await _a_proposal(postgres_kernel)
    await _answered_with_a_proposal(postgres_kernel, inquiry_id, proposal_id)

    closed = await bind_close(postgres_kernel)(
        ClosePursuitRound(pursuit_id=pursuit_id, round_index=0),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )

    assert closed.dispatched_id is not None
    pursuit = await load_pursuit(postgres_kernel.event_store, pursuit_id)
    proposal = await load_proposal(postgres_kernel.event_store, proposal_id)
    dispatched = await load_execution(postgres_kernel.event_store, closed.dispatched_id)
    assert pursuit is not None
    assert proposal is not None
    assert dispatched is not None
    assert pursuit.rounds[0].dispatched_id == closed.dispatched_id
    assert proposal.status is ProposalStatus.ADOPTED
    assert dispatched.beamline.value == "2-bm"
    procedure = await load_procedure(postgres_kernel.event_store, dispatched.procedure_id)
    assert procedure is not None


async def test_a_round_refused_at_the_close_dispatches_nothing(
    postgres_kernel: Kernel, db_pool: asyncpg.Pool
) -> None:
    """The refusal that matters, because everything before it has already
    been decided. The proposal was adopted once by somebody else, so the
    adoption decider refuses, and the procedure and execution composed a
    line earlier must not survive it."""
    pursuit_id = await _a_pursuit(postgres_kernel)
    inquiry_id = await bind_open_round(postgres_kernel)(
        OpenPursuitRound(pursuit_id=pursuit_id, execution_id=await _an_execution(postgres_kernel)),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )
    proposal_id = await _a_proposal(postgres_kernel)
    await _answered_with_a_proposal(postgres_kernel, inquiry_id, proposal_id)
    await bind_adopt(postgres_kernel)(
        AdoptProposal(proposal_id=proposal_id, beamline="7-bm", scopes=("7bma:det:",)),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )
    procedures = await _stream_count(db_pool, PROCEDURE_STREAM_TYPE)
    executions = await _stream_count(db_pool, EXECUTION_STREAM_TYPE)

    with pytest.raises(ProposalCannotBeAdoptedError):
        await bind_close(postgres_kernel)(
            ClosePursuitRound(pursuit_id=pursuit_id, round_index=0),
            principal_id=uuid4(),
            correlation_id=uuid4(),
        )

    assert await _stream_count(db_pool, PROCEDURE_STREAM_TYPE) == procedures
    assert await _stream_count(db_pool, EXECUTION_STREAM_TYPE) == executions
    pursuit = await load_pursuit(postgres_kernel.event_store, pursuit_id)
    assert pursuit is not None
    assert pursuit.rounds[0].is_open, "a refused close leaves the round open to try again"


async def test_two_callers_closing_one_round_at_once_dispatch_exactly_one_run(
    postgres_kernel: Kernel, db_pool: asyncpg.Pool
) -> None:
    """The four-stream version of the race, held at the load the same way.

    Both callers compose a procedure and an execution before either
    appends. The loser must have written neither, because a beamline
    walking a run that no round points at is the failure this whole slice
    is one transaction to avoid.
    """
    pursuit_id = await _a_pursuit(postgres_kernel)
    inquiry_id = await bind_open_round(postgres_kernel)(
        OpenPursuitRound(pursuit_id=pursuit_id, execution_id=await _an_execution(postgres_kernel)),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )
    await _answered_with_a_proposal(postgres_kernel, inquiry_id, await _a_proposal(postgres_kernel))
    procedures = await _stream_count(db_pool, PROCEDURE_STREAM_TYPE)
    executions = await _stream_count(db_pool, EXECUTION_STREAM_TYPE)
    racing = replace(
        postgres_kernel,
        event_store=cast(
            "EventStore",
            HeldAtTheLoad(postgres_kernel.event_store, asyncio.Barrier(2), on=PURSUIT_STREAM_TYPE),
        ),
    )
    close = bind_close(racing)

    async def close_one() -> object:
        return await close(
            ClosePursuitRound(pursuit_id=pursuit_id, round_index=0),
            principal_id=uuid4(),
            correlation_id=uuid4(),
        )

    outcomes = await asyncio.gather(close_one(), close_one(), return_exceptions=True)

    won = [outcome for outcome in outcomes if not isinstance(outcome, BaseException)]
    assert len(won) == 1, f"exactly one caller may close the round, got {outcomes}"
    assert await _stream_count(db_pool, PROCEDURE_STREAM_TYPE) == procedures + 1, (
        "the loser composed a procedure and must not have written it"
    )
    assert await _stream_count(db_pool, EXECUTION_STREAM_TYPE) == executions + 1, (
        "the loser dispatched an execution and must not have written it"
    )
