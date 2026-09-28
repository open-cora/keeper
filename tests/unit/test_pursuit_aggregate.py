"""The Pursuit aggregate: its value objects, its budget, and its fold.

The aggregate tier, so nothing here goes through a handler or a port.
What is checked is the part that has to hold however a pursuit was
written: that the bounds refuse what they say they refuse, that a budget
bounding nothing cannot exist, and that every closed type is rebuilt on
the way out of the log rather than trusted.

That last one carries more weight in this context than elsewhere. A
pursuit is a standing authorization, so a scope list or a budget that
degraded in storage would widen what a machine may do, silently and with
nobody present. The fold is where that is caught, which is why the
round-trip tests below go through `to_payload` and `from_stored` rather
than constructing events directly.
"""

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest

from keeper.infrastructure.ports.event_store import StoredEvent
from keeper.pursuit.aggregates.pursuit import (
    PURSUIT_GOAL_MAX_LENGTH,
    PURSUIT_MAX_SCOPES,
    PURSUIT_SCOPE_MAX_LENGTH,
    Budget,
    BudgetDimension,
    InvalidPursuitBeamlineError,
    InvalidPursuitBudgetError,
    InvalidPursuitGoalError,
    InvalidPursuitScopesError,
    PursuitBeamline,
    PursuitGoal,
    PursuitStarted,
    PursuitStatus,
    PursuitWithdrawn,
    evolve,
    fold,
    from_stored,
    to_payload,
    validate_scopes,
)

pytestmark = pytest.mark.unit

_WHEN = datetime(2026, 9, 27, 9, 0, tzinfo=UTC)


def _started(**overrides: Any) -> PursuitStarted:
    fields: dict[str, Any] = {
        "pursuit_id": uuid4(),
        "actor_id": uuid4(),
        "goal": "find the edge of the useful exposure range",
        "beamline": "2-bm",
        "scopes": ("2bmb:m1", "2bmb:det"),
        "budget": {"Rounds": 8, "Tokens": 400000},
        "occurred_at": _WHEN,
    }
    fields.update(overrides)
    return PursuitStarted(**fields)


def _as_stored(event: PursuitStarted | PursuitWithdrawn) -> StoredEvent:
    """Put an event through the payload the store would actually hold.

    Constructing the event again by hand would test the constructor twice
    and the serializer not at all, and the serializer is the half that can
    lose a scope.
    """
    return StoredEvent(
        position=1,
        event_id=uuid4(),
        stream_type="Pursuit",
        stream_id=event.pursuit_id,
        version=1,
        event_type=type(event).__name__,
        schema_version=1,
        payload=to_payload(event),
        correlation_id=uuid4(),
        causation_id=None,
        occurred_at=event.occurred_at,
        recorded_at=event.occurred_at,
    )


def test_a_goal_longer_than_the_bound_is_refused() -> None:
    with pytest.raises(InvalidPursuitGoalError):
        PursuitGoal("x" * (PURSUIT_GOAL_MAX_LENGTH + 1))


def test_a_goal_that_is_only_whitespace_is_refused() -> None:
    """A pursuit with nothing stated as its goal would leave the thinker's
    Stop conclusion with nothing to be met."""
    with pytest.raises(InvalidPursuitGoalError):
        PursuitGoal("   ")


def test_a_goal_is_kept_trimmed() -> None:
    assert PursuitGoal("  find the edge  ").value == "find the edge"


def test_a_beamline_that_is_empty_is_refused() -> None:
    with pytest.raises(InvalidPursuitBeamlineError):
        PursuitBeamline("")


def test_a_budget_that_bounds_nothing_is_refused() -> None:
    """The one thing this aggregate exists to make impossible."""
    with pytest.raises(InvalidPursuitBudgetError):
        Budget({})


@pytest.mark.parametrize("limit", [0, -1])
def test_a_budget_with_a_limit_that_is_not_positive_is_refused(limit: int) -> None:
    """Zero is refused as well as negative, because a pursuit that may run
    zero rounds is a pursuit nobody meant to authorize."""
    with pytest.raises(InvalidPursuitBudgetError):
        Budget({BudgetDimension.ROUNDS: limit})


def test_a_budget_may_bound_one_dimension_or_several() -> None:
    assert Budget({BudgetDimension.TOKENS: 1}).limits == {BudgetDimension.TOKENS: 1}
    several = Budget({BudgetDimension.ROUNDS: 8, BudgetDimension.BEAM_SECONDS: 3600})
    assert len(several.limits) == 2


def test_no_scopes_at_all_is_refused() -> None:
    """A pursuit authorized over nothing could dispatch nothing."""
    with pytest.raises(InvalidPursuitScopesError):
        validate_scopes(())


def test_more_scopes_than_the_bound_is_refused() -> None:
    with pytest.raises(InvalidPursuitScopesError):
        validate_scopes(tuple(f"scope-{index}" for index in range(PURSUIT_MAX_SCOPES + 1)))


def test_a_scope_longer_than_the_bound_is_refused() -> None:
    with pytest.raises(InvalidPursuitScopesError):
        validate_scopes(("x" * (PURSUIT_SCOPE_MAX_LENGTH + 1),))


def test_an_empty_scope_beside_a_good_one_is_refused() -> None:
    """Refused rather than dropped. A caller that sent a blank meant
    something by it, and silently authorizing the rest would be this system
    deciding which half of a permission it liked."""
    with pytest.raises(InvalidPursuitScopesError):
        validate_scopes(("2bmb:m1", "  "))


def test_scopes_are_kept_trimmed() -> None:
    assert validate_scopes((" 2bmb:m1 ",)) == ("2bmb:m1",)


def test_a_started_pursuit_folds_to_running_with_everything_it_was_given() -> None:
    event = _started()

    pursuit = fold([from_stored(_as_stored(event))])

    assert pursuit is not None
    assert pursuit.status is PursuitStatus.RUNNING
    assert pursuit.is_running
    assert pursuit.goal.value == "find the edge of the useful exposure range"
    assert pursuit.beamline.value == "2-bm"
    assert pursuit.scopes == ("2bmb:m1", "2bmb:det")
    assert pursuit.budget.limits == {
        BudgetDimension.ROUNDS: 8,
        BudgetDimension.TOKENS: 400000,
    }
    assert pursuit.stopped_by is None


def test_the_started_moment_becomes_the_pursuits_own_start() -> None:
    """One budget dimension is measured against it, so it is state rather
    than something a reader fetches off the envelope."""
    pursuit = fold([from_stored(_as_stored(_started()))])

    assert pursuit is not None
    assert pursuit.started_at == _WHEN


def test_withdrawing_stops_the_pursuit_and_names_who_did_it() -> None:
    started = _started()
    stopper = uuid4()
    withdrawn = PursuitWithdrawn(pursuit_id=started.pursuit_id, actor_id=stopper, occurred_at=_WHEN)

    pursuit = fold([from_stored(_as_stored(started)), from_stored(_as_stored(withdrawn))])

    assert pursuit is not None
    assert pursuit.status is PursuitStatus.STOPPED
    assert not pursuit.is_running
    assert pursuit.stopped_by == stopper
    assert pursuit.actor_id != stopper, "the fixture's two actors must differ for this to mean any"


def test_stopping_is_the_only_terminal_status() -> None:
    assert PursuitStatus.STOPPED.is_terminal
    assert not PursuitStatus.RUNNING.is_terminal


def test_an_empty_stream_folds_to_nothing() -> None:
    assert fold([]) is None


def test_a_budget_that_degraded_in_storage_fails_at_the_fold() -> None:
    """The check that matters most in this context. A limit that went to
    zero between the write and the read would be an authorization nobody
    granted, and it fails here rather than reaching a caller."""
    poisoned = _as_stored(_started())
    poisoned.payload["budget"] = {"Rounds": 0}

    with pytest.raises(InvalidPursuitBudgetError):
        evolve(None, from_stored(poisoned))


def test_a_dimension_no_longer_in_the_enum_fails_at_the_fold() -> None:
    poisoned = _as_stored(_started())
    poisoned.payload["budget"] = {"Neutrons": 4}

    with pytest.raises(ValueError, match="Neutrons"):
        evolve(None, from_stored(poisoned))


def test_a_scope_that_degraded_in_storage_fails_at_the_fold() -> None:
    poisoned = _as_stored(_started())
    poisoned.payload["scopes"] = []

    with pytest.raises(InvalidPursuitScopesError):
        evolve(None, from_stored(poisoned))


def test_a_withdrawal_with_no_pursuit_before_it_refuses_to_fold() -> None:
    """Nothing can be revoked that was never authorized, and a fold that
    invented a pursuit here would be inventing the authorization too."""
    withdrawn = PursuitWithdrawn(pursuit_id=uuid4(), actor_id=uuid4(), occurred_at=_WHEN)

    with pytest.raises(ValueError, match="PursuitWithdrawn"):
        evolve(None, from_stored(_as_stored(withdrawn)))


def test_an_event_type_this_aggregate_never_wrote_is_refused() -> None:
    with pytest.raises(ValueError, match="Unknown Pursuit event_type"):
        from_stored(
            StoredEvent(
                position=1,
                event_id=uuid4(),
                stream_type="Pursuit",
                stream_id=uuid4(),
                version=1,
                event_type="PursuitAbandoned",
                schema_version=1,
                payload={},
                correlation_id=uuid4(),
                causation_id=None,
                occurred_at=_WHEN,
                recorded_at=_WHEN,
            )
        )


def test_a_payload_missing_a_field_names_the_event_rather_than_the_field() -> None:
    broken = _as_stored(_started())
    del broken.payload["beamline"]

    with pytest.raises(ValueError, match="PursuitStarted"):
        from_stored(broken)
