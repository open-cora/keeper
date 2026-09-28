"""The three Pursuit handlers, against in-process stores.

One file for three handlers, because what is worth testing about them is
shared and small: this context reaches into no sibling, so there is no
cross-context load to get wrong and no 404 from somebody else's aggregate.
What is left is the part a decider never sees.

Four things, then. That the actor on the record is the authenticated
principal and not anything a caller sent, which matters more here than
anywhere else because the actor IS the authorization. Which moment each
handler stamps, which is R8 showing up as behaviour rather than as a field
list. That withdrawing appends at the version it folded from, which is the
whole concurrency story in a context that has no claim. And that every
handler asks the authorization port first.
"""

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from keeper.counsel.aggregates.inquiry import INQUIRY_STREAM_TYPE, load_inquiry
from keeper.execution.aggregates.execution import ExecutionNotFoundError
from keeper.execution.aggregates.procedure import MoveStep
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
from keeper.pursuit.aggregates.pursuit import (
    PURSUIT_STREAM_TYPE,
    Budget,
    BudgetDimension,
    InvalidPursuitChargeError,
    Pursuit,
    PursuitAlreadyExistsError,
    PursuitBeamline,
    PursuitCannotBeWithdrawnError,
    PursuitGoal,
    PursuitNotFoundError,
    PursuitRoundCannotBeOpenedError,
    PursuitStatus,
    load_pursuit,
)
from keeper.pursuit.features.charge_pursuit import ChargePursuit
from keeper.pursuit.features.charge_pursuit import bind as bind_charge
from keeper.pursuit.features.get_pursuit import GetPursuit
from keeper.pursuit.features.get_pursuit import bind as bind_get
from keeper.pursuit.features.open_pursuit_round import OpenPursuitRound
from keeper.pursuit.features.open_pursuit_round import bind as bind_open_round
from keeper.pursuit.features.start_pursuit import StartPursuit
from keeper.pursuit.features.start_pursuit import bind as bind_start
from keeper.pursuit.features.start_pursuit import decide as decide_start
from keeper.pursuit.features.withdraw_pursuit import WithdrawPursuit
from keeper.pursuit.features.withdraw_pursuit import bind as bind_withdraw
from keeper.shared.reserved_ids import NIL_SENTINEL_ID
from keeper.shared.unauthorized import UnauthorizedError

pytestmark = pytest.mark.unit

_CLOCK_NOW = datetime(2026, 9, 27, 9, 0, tzinfo=UTC)
"""What the clock says, deliberately not a time any caller could report.

Neither command here accepts one, which is the thing these tests are
checking, so a caller has nowhere to put a different moment even if it
wanted to.
"""

_GOAL = PursuitGoal("find the edge of the useful exposure range")
_BEAMLINE = PursuitBeamline("2-bm")
_SCOPES = ("2bmb:m1", "2bmb:det")
_BUDGET = Budget({BudgetDimension.ROUNDS: 8, BudgetDimension.TOKENS: 400000})


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


async def _a_pursuit(deps: Kernel, *, principal_id: UUID | None = None) -> UUID:
    return await bind_start(deps)(
        StartPursuit(goal=_GOAL, beamline=_BEAMLINE, scopes=_SCOPES, budget=_BUDGET),
        principal_id=principal_id or uuid4(),
        correlation_id=uuid4(),
    )


async def test_starting_writes_one_event_and_returns_its_id() -> None:
    deps = _kernel()

    pursuit_id = await _a_pursuit(deps)

    stored, _version = await deps.event_store.load(PURSUIT_STREAM_TYPE, pursuit_id)
    assert [row.event_type for row in stored] == ["PursuitStarted"]


async def test_the_authorizing_actor_is_the_principal_and_not_the_command() -> None:
    """The field the whole aggregate rests on. A caller that could name
    somebody else as the author of a standing permission could grant one in
    their name."""
    deps = _kernel()
    person = uuid4()

    pursuit_id = await _a_pursuit(deps, principal_id=person)

    pursuit = await load_pursuit(deps.event_store, pursuit_id)
    assert pursuit is not None
    assert pursuit.actor_id == person


async def test_starting_stamps_the_clock_because_the_command_carries_no_time() -> None:
    """Authorizing is a speech act performed here, so the moment this
    system writes the record IS the moment it happened."""
    deps = _kernel()

    pursuit_id = await _a_pursuit(deps)

    stored, _version = await deps.event_store.load(PURSUIT_STREAM_TYPE, pursuit_id)
    assert stored[0].occurred_at == _CLOCK_NOW


async def test_a_started_pursuit_reads_back_running_with_its_whole_authorization() -> None:
    deps = _kernel()
    pursuit_id = await _a_pursuit(deps)

    pursuit = await bind_get(deps)(
        GetPursuit(pursuit_id=pursuit_id), principal_id=uuid4(), correlation_id=uuid4()
    )

    assert pursuit.status is PursuitStatus.RUNNING
    assert (pursuit.beamline.value, pursuit.scopes) == ("2-bm", _SCOPES)
    assert pursuit.budget.limits[BudgetDimension.ROUNDS] == 8


async def test_starting_against_an_id_that_already_has_history_is_refused() -> None:
    """Unreachable through the handler, which mints a fresh id, so the
    decider is asked directly. It states the precondition it relies on
    rather than assuming it."""
    existing = Pursuit(
        id=uuid4(),
        actor_id=uuid4(),
        goal=_GOAL,
        beamline=_BEAMLINE,
        scopes=_SCOPES,
        budget=_BUDGET,
        started_at=_CLOCK_NOW,
        status=PursuitStatus.RUNNING,
    )

    with pytest.raises(PursuitAlreadyExistsError):
        decide_start(
            existing,
            StartPursuit(goal=_GOAL, beamline=_BEAMLINE, scopes=_SCOPES, budget=_BUDGET),
            actor_id=uuid4(),
            now=_CLOCK_NOW,
            new_id=uuid4(),
        )


async def test_withdrawing_stops_the_pursuit_and_records_who_stopped_it() -> None:
    deps = _kernel()
    author = uuid4()
    stopper = uuid4()
    pursuit_id = await _a_pursuit(deps, principal_id=author)

    await bind_withdraw(deps)(
        WithdrawPursuit(pursuit_id=pursuit_id), principal_id=stopper, correlation_id=uuid4()
    )

    pursuit = await load_pursuit(deps.event_store, pursuit_id)
    assert pursuit is not None
    assert pursuit.status is PursuitStatus.STOPPED
    assert (pursuit.actor_id, pursuit.stopped_by) == (author, stopper)


async def test_somebody_other_than_the_author_may_withdraw() -> None:
    """The ordinary case rather than the strange one. Requiring the author
    would mean the one person who cannot be reached is the only one who can
    stop an overnight loop."""
    deps = _kernel()
    pursuit_id = await _a_pursuit(deps, principal_id=uuid4())

    await bind_withdraw(deps)(
        WithdrawPursuit(pursuit_id=pursuit_id), principal_id=uuid4(), correlation_id=uuid4()
    )

    pursuit = await load_pursuit(deps.event_store, pursuit_id)
    assert pursuit is not None
    assert not pursuit.is_running


async def test_withdrawing_appends_at_the_version_it_folded_from() -> None:
    """The whole concurrency story in a context with no claim. Two people
    stopping one pursuit fold the same running state and append at the same
    version, and the store lets exactly one through."""
    deps = _kernel()
    pursuit_id = await _a_pursuit(deps)

    await bind_withdraw(deps)(
        WithdrawPursuit(pursuit_id=pursuit_id), principal_id=uuid4(), correlation_id=uuid4()
    )

    stored, version = await deps.event_store.load(PURSUIT_STREAM_TYPE, pursuit_id)
    assert [row.event_type for row in stored] == ["PursuitStarted", "PursuitWithdrawn"]
    assert version == 2


async def test_withdrawing_twice_is_refused_rather_than_ignored() -> None:
    """A second withdrawal would name a second person and a second moment,
    and the record would stop saying who ended the authorization."""
    deps = _kernel()
    pursuit_id = await _a_pursuit(deps)
    await bind_withdraw(deps)(
        WithdrawPursuit(pursuit_id=pursuit_id), principal_id=uuid4(), correlation_id=uuid4()
    )

    with pytest.raises(PursuitCannotBeWithdrawnError):
        await bind_withdraw(deps)(
            WithdrawPursuit(pursuit_id=pursuit_id), principal_id=uuid4(), correlation_id=uuid4()
        )


async def test_withdrawing_a_pursuit_that_was_never_started_is_not_found() -> None:
    deps = _kernel()

    with pytest.raises(PursuitNotFoundError):
        await bind_withdraw(deps)(
            WithdrawPursuit(pursuit_id=uuid4()), principal_id=uuid4(), correlation_id=uuid4()
        )


async def test_reading_a_pursuit_that_was_never_started_is_not_found() -> None:
    deps = _kernel()

    with pytest.raises(PursuitNotFoundError):
        await bind_get(deps)(
            GetPursuit(pursuit_id=uuid4()), principal_id=uuid4(), correlation_id=uuid4()
        )


async def test_starting_asks_the_authorization_port_before_anything_else() -> None:
    """A refused start must leave no stream behind, because a pursuit
    written and then refused is a permission that exists."""
    deps = _kernel(authz=_DenyAllAuthorize())

    with pytest.raises(UnauthorizedError):
        await _a_pursuit(deps)

    assert isinstance(deps.event_store, InMemoryEventStore)
    assert not deps.event_store.stream_ids(PURSUIT_STREAM_TYPE)


async def test_withdrawing_asks_the_authorization_port_first() -> None:
    allowed = _kernel()
    pursuit_id = await _a_pursuit(allowed)
    refused = _kernel(authz=_DenyAllAuthorize())

    with pytest.raises(UnauthorizedError):
        await bind_withdraw(refused)(
            WithdrawPursuit(pursuit_id=pursuit_id), principal_id=uuid4(), correlation_id=uuid4()
        )


async def test_reading_asks_the_authorization_port_first() -> None:
    deps = _kernel(authz=_DenyAllAuthorize())

    with pytest.raises(UnauthorizedError):
        await bind_get(deps)(
            GetPursuit(pursuit_id=uuid4()), principal_id=uuid4(), correlation_id=uuid4()
        )


async def _an_execution(deps: Kernel) -> UUID:
    """Dispatch something real for a round to observe.

    The whole chain runs, because opening a round loads the execution and
    counts the steps it was dispatched with: that number is the denominator
    of the observation boundary the answer will be read against, and there
    is nothing to fake short of dispatching something.
    """
    procedure_id = await bind_define_procedure(deps)(
        DefineProcedure(
            name="align_then_scan",
            beamline="2-bm",
            steps=(MoveStep(record="2bmb:m1", to=0.0), MoveStep(record="2bmb:m2", to=5.0)),
        ),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )
    return await bind_dispatch_execution(deps)(
        DispatchExecution(procedure_id=procedure_id),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )


async def _a_round(deps: Kernel, pursuit_id: UUID, execution_id: UUID, **kw: UUID) -> UUID:
    return await bind_open_round(deps)(
        OpenPursuitRound(pursuit_id=pursuit_id, execution_id=execution_id),
        principal_id=kw.get("principal_id", uuid4()),
        correlation_id=uuid4(),
    )


async def test_opening_a_round_writes_both_streams_and_returns_the_inquiry() -> None:
    deps = _kernel()
    pursuit_id = await _a_pursuit(deps)
    execution_id = await _an_execution(deps)

    inquiry_id = await _a_round(deps, pursuit_id, execution_id)

    on_the_pursuit, _v = await deps.event_store.load(PURSUIT_STREAM_TYPE, pursuit_id)
    on_the_inquiry, _w = await deps.event_store.load(INQUIRY_STREAM_TYPE, inquiry_id)
    assert [row.event_type for row in on_the_pursuit] == ["PursuitStarted", "PursuitRoundOpened"]
    assert [row.event_type for row in on_the_inquiry] == ["InquiryMade"]


async def test_the_question_a_round_puts_is_the_pursuits_own_goal() -> None:
    """A caller that could word the question would be able to ask something
    the person who authorized the pursuit did not."""
    deps = _kernel()
    pursuit_id = await _a_pursuit(deps)
    execution_id = await _an_execution(deps)

    inquiry_id = await _a_round(deps, pursuit_id, execution_id)

    inquiry = await load_inquiry(deps.event_store, inquiry_id)
    assert inquiry is not None
    assert inquiry.objective.value == _GOAL.value
    assert inquiry.execution_id == execution_id


async def test_a_round_captures_the_step_count_the_boundary_is_read_against() -> None:
    deps = _kernel()
    pursuit_id = await _a_pursuit(deps)
    execution_id = await _an_execution(deps)

    inquiry = await load_inquiry(deps.event_store, await _a_round(deps, pursuit_id, execution_id))

    assert inquiry is not None
    assert inquiry.execution_step_count == 2


async def test_the_round_and_the_inquiry_cite_each_other() -> None:
    deps = _kernel()
    pursuit_id = await _a_pursuit(deps)
    execution_id = await _an_execution(deps)

    inquiry_id = await _a_round(deps, pursuit_id, execution_id)

    pursuit = await load_pursuit(deps.event_store, pursuit_id)
    assert pursuit is not None
    assert pursuit.rounds[0].inquiry_id == inquiry_id
    assert pursuit.rounds[0].execution_id == execution_id


async def test_a_second_round_about_one_execution_is_refused() -> None:
    """The retry guard. A driver that crashed and came back cannot spend
    the budget twice on the same question, which is what lets it be run
    more than once with no coordination."""
    deps = _kernel()
    pursuit_id = await _a_pursuit(deps)
    execution_id = await _an_execution(deps)
    await _a_round(deps, pursuit_id, execution_id)

    with pytest.raises(PursuitRoundCannotBeOpenedError, match="already asked"):
        await _a_round(deps, pursuit_id, execution_id)


async def test_a_round_on_a_withdrawn_pursuit_is_refused() -> None:
    deps = _kernel()
    pursuit_id = await _a_pursuit(deps)
    execution_id = await _an_execution(deps)
    await bind_withdraw(deps)(
        WithdrawPursuit(pursuit_id=pursuit_id), principal_id=uuid4(), correlation_id=uuid4()
    )

    with pytest.raises(PursuitRoundCannotBeOpenedError, match="stopped"):
        await _a_round(deps, pursuit_id, execution_id)


async def test_a_round_past_the_budget_is_refused_and_names_the_dimension() -> None:
    """The refusal a person has to act on, so it says which limit was
    reached rather than that some limit was."""
    deps = _kernel()
    pursuit_id = await bind_start(deps)(
        StartPursuit(
            goal=_GOAL,
            beamline=_BEAMLINE,
            scopes=_SCOPES,
            budget=Budget({BudgetDimension.ROUNDS: 1}),
        ),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )
    await _a_round(deps, pursuit_id, await _an_execution(deps))

    with pytest.raises(PursuitRoundCannotBeOpenedError, match="Rounds"):
        await _a_round(deps, pursuit_id, await _an_execution(deps))


async def test_a_round_naming_an_execution_that_does_not_exist_writes_nothing() -> None:
    """Both halves must fail together, and the inquiry is the one that
    would otherwise land: it is a genesis on a fresh stream, so nothing
    refuses it but the missing execution."""
    deps = _kernel()
    pursuit_id = await _a_pursuit(deps)

    with pytest.raises(ExecutionNotFoundError):
        await _a_round(deps, pursuit_id, uuid4())

    assert isinstance(deps.event_store, InMemoryEventStore)
    assert not deps.event_store.stream_ids(INQUIRY_STREAM_TYPE)
    pursuit = await load_pursuit(deps.event_store, pursuit_id)
    assert pursuit is not None
    assert pursuit.rounds == ()


async def test_a_round_on_a_pursuit_that_was_never_started_is_not_found() -> None:
    deps = _kernel()

    with pytest.raises(PursuitNotFoundError):
        await _a_round(deps, uuid4(), await _an_execution(deps))


async def test_opening_a_round_asks_the_authorization_port_first() -> None:
    allowed = _kernel()
    pursuit_id = await _a_pursuit(allowed)
    execution_id = await _an_execution(allowed)
    refused = _kernel(authz=_DenyAllAuthorize())

    with pytest.raises(UnauthorizedError):
        await bind_open_round(refused)(
            OpenPursuitRound(pursuit_id=pursuit_id, execution_id=execution_id),
            principal_id=uuid4(),
            correlation_id=uuid4(),
        )


async def _charge(deps: Kernel, pursuit_id: UUID, dimension: BudgetDimension, amount: int) -> int:
    return await bind_charge(deps)(
        ChargePursuit(pursuit_id=pursuit_id, dimension=dimension, amount=amount),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )


async def test_charging_adds_and_answers_with_the_new_total() -> None:
    deps = _kernel()
    pursuit_id = await _a_pursuit(deps)

    first = await _charge(deps, pursuit_id, BudgetDimension.TOKENS, 12500)
    second = await _charge(deps, pursuit_id, BudgetDimension.TOKENS, 500)

    assert (first, second) == (12500, 13000)


async def test_charging_stamps_the_clock_when_the_caller_names_no_moment() -> None:
    deps = _kernel()
    pursuit_id = await _a_pursuit(deps)

    await _charge(deps, pursuit_id, BudgetDimension.TOKENS, 10)

    stored, _version = await deps.event_store.load(PURSUIT_STREAM_TYPE, pursuit_id)
    assert stored[-1].occurred_at == _CLOCK_NOW


async def test_charging_stamps_the_moment_the_caller_gave() -> None:
    """The one describing command here. Beam seconds were consumed out in
    the world, and the caller was there while this system was not."""
    deps = _kernel()
    pursuit_id = await bind_start(deps)(
        StartPursuit(
            goal=_GOAL,
            beamline=_BEAMLINE,
            scopes=_SCOPES,
            budget=Budget({BudgetDimension.BEAM_SECONDS: 3600}),
        ),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )
    measured = datetime(2026, 9, 26, 22, 30, tzinfo=UTC)

    await bind_charge(deps)(
        ChargePursuit(
            pursuit_id=pursuit_id,
            dimension=BudgetDimension.BEAM_SECONDS,
            amount=90,
            occurred_at=measured,
        ),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )

    stored, _version = await deps.event_store.load(PURSUIT_STREAM_TYPE, pursuit_id)
    assert stored[-1].occurred_at == measured
    assert measured != _CLOCK_NOW


async def test_a_stopped_pursuit_is_charged_like_any_other() -> None:
    """What this records happened out in the world. Beam seconds from the
    run that was in flight when somebody withdrew the pursuit are real
    seconds, and refusing them would make the record disagree."""
    deps = _kernel()
    pursuit_id = await _a_pursuit(deps)
    await bind_withdraw(deps)(
        WithdrawPursuit(pursuit_id=pursuit_id), principal_id=uuid4(), correlation_id=uuid4()
    )

    assert await _charge(deps, pursuit_id, BudgetDimension.TOKENS, 40) == 40


@pytest.mark.parametrize("amount", [0, -1])
async def test_charging_an_amount_that_is_not_positive_is_refused(amount: int) -> None:
    """A correction that silently reduces what a loop has spent is a way to
    extend a budget without anybody authorizing more."""
    deps = _kernel()
    pursuit_id = await _a_pursuit(deps)

    with pytest.raises(InvalidPursuitChargeError, match="positive"):
        await _charge(deps, pursuit_id, BudgetDimension.TOKENS, amount)


async def test_charging_a_dimension_this_system_counts_for_itself_is_refused() -> None:
    deps = _kernel()
    pursuit_id = await _a_pursuit(deps)

    with pytest.raises(InvalidPursuitChargeError, match="Rounds"):
        await _charge(deps, pursuit_id, BudgetDimension.ROUNDS, 3)


async def test_charging_a_dimension_the_pursuit_was_not_bounded_in_is_refused() -> None:
    """Almost certainly a caller naming the wrong pursuit, and a number
    nothing will ever read accumulating on a record nobody can edit."""
    deps = _kernel()
    pursuit_id = await _a_pursuit(deps)

    with pytest.raises(InvalidPursuitChargeError, match="BeamSeconds"):
        await _charge(deps, pursuit_id, BudgetDimension.BEAM_SECONDS, 90)


async def test_charging_a_pursuit_that_was_never_started_is_not_found() -> None:
    deps = _kernel()

    with pytest.raises(PursuitNotFoundError):
        await _charge(deps, uuid4(), BudgetDimension.TOKENS, 10)


async def test_charging_asks_the_authorization_port_first() -> None:
    deps = _kernel(authz=_DenyAllAuthorize())

    with pytest.raises(UnauthorizedError):
        await _charge(deps, uuid4(), BudgetDimension.TOKENS, 10)
