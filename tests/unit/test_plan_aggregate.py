"""The Plan aggregate: its name value object, its fold, and its round trip.

The round trip is the load-bearing one. A payload leaves as primitives
and comes back as a value object, and the two halves are written in
different modules, so nothing but a test run against both at once says
they still agree.
"""

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest

from keeper.execution.aggregates.plan import (
    PLAN_NAME_MAX_LENGTH,
    PLAN_STREAM_TYPE,
    InvalidPlanNameError,
    PlanDefined,
    PlanName,
    fold,
    from_stored,
    to_payload,
)
from keeper.infrastructure.ports.event_store import StoredEvent

pytestmark = pytest.mark.unit

_WHEN = datetime(2026, 9, 18, 9, 30, tzinfo=UTC)

_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {"exposure_seconds": {"type": "number", "minimum": 0}},
    "required": ["exposure_seconds"],
}


def _stored(event_type: str, payload: dict[str, object]) -> StoredEvent:
    """A stored row carrying the given type and payload, envelope filled in."""
    return StoredEvent(
        position=1,
        event_id=uuid4(),
        stream_type=PLAN_STREAM_TYPE,
        stream_id=uuid4(),
        version=1,
        event_type=event_type,
        schema_version=1,
        payload=dict(payload),
        correlation_id=uuid4(),
        causation_id=None,
        occurred_at=_WHEN,
        recorded_at=_WHEN,
    )


def _defined(name: str = "count") -> PlanDefined:
    return PlanDefined(
        plan_id=uuid4(),
        plan_name=name,
        parameters_schema=_SCHEMA,
        occurred_at=_WHEN,
    )


def test_a_plan_name_is_trimmed_on_construction() -> None:
    assert PlanName("  count  ").value == "count"


def test_a_plan_name_that_is_only_whitespace_is_refused() -> None:
    with pytest.raises(InvalidPlanNameError):
        PlanName("   ")


def test_a_plan_name_over_the_length_bound_is_refused() -> None:
    with pytest.raises(InvalidPlanNameError):
        PlanName("x" * (PLAN_NAME_MAX_LENGTH + 1))


def test_a_plan_name_at_the_length_bound_is_accepted() -> None:
    """The bound is inclusive, which an off-by-one would quietly move."""
    at_the_bound = "x" * PLAN_NAME_MAX_LENGTH
    assert PlanName(at_the_bound).value == at_the_bound


def test_the_stored_payload_carries_the_name_under_a_qualified_key() -> None:
    """The payload boundary, asserted on the payload itself.

    `plan_name` rather than `name` is what keeps this row past the
    personal-data check, and that check reads the event class, not this
    dict. A payload key renamed without the field would pass there and
    break only the round trip, which is a longer way round to the same
    news.
    """
    event = _defined()

    assert to_payload(event) == {
        "plan_id": str(event.plan_id),
        "plan_name": "count",
        "parameters_schema": _SCHEMA,
        "occurred_at": _WHEN.isoformat(),
    }


def test_folding_the_genesis_event_gives_the_plan_it_describes() -> None:
    event = _defined()

    plan = fold([event])

    assert plan is not None
    assert plan.id == event.plan_id
    assert plan.name == PlanName("count")
    assert plan.parameters_schema == _SCHEMA


def test_folding_an_empty_stream_gives_no_plan() -> None:
    assert fold([]) is None


def test_the_folded_schema_is_not_the_payload_dict_it_came_from() -> None:
    """Shallow copy on fold, so neither side can mutate the other.

    The immutable-collection rule in docs/reference/modeling.md cannot
    cover a JSON Schema field, because a schema is freeform by nature
    and no immutable type fits it. The copy is the defence that replaces
    it, and an aliasing bug here is silent: the state would look right
    until something wrote through one reference and changed the other.
    """
    event = _defined()

    plan = fold([event])

    assert plan is not None
    assert plan.parameters_schema == event.parameters_schema
    assert plan.parameters_schema is not event.parameters_schema


def test_an_event_survives_the_round_trip_through_its_stored_payload() -> None:
    event = _defined("grid_scan")

    assert from_stored(_stored("PlanDefined", to_payload(event))) == event


def test_a_stored_row_of_an_unknown_event_type_is_refused() -> None:
    with pytest.raises(ValueError, match="Unknown Plan event_type"):
        from_stored(_stored("PlanRetired", to_payload(_defined())))


def test_a_stored_row_missing_a_field_is_refused_by_event_not_by_field() -> None:
    """The wrap is what makes the error name the event.

    Without it a bad row raises `KeyError` from inside the builder, which
    says which field was missing and not which event could not be
    rebuilt. The caller has the row and can find the field; what it
    cannot recover is the shape the row was meant to have.
    """
    payload = to_payload(_defined())
    del payload["plan_name"]

    with pytest.raises(ValueError, match="Malformed PlanDefined"):
        from_stored(_stored("PlanDefined", payload))


def test_a_stored_row_whose_name_no_longer_passes_the_bound_fails_the_fold() -> None:
    """Re-validation on the way out, not just on the way in.

    A row can only hold a name the decider accepted, so this state is
    unreachable through the API today. It becomes reachable the day the
    bound is tightened, and the fold refusing is what turns that into a
    visible failure rather than a plan whose name nothing could have
    written.
    """
    payload = to_payload(_defined())
    payload["plan_name"] = "x" * (PLAN_NAME_MAX_LENGTH + 1)

    with pytest.raises(InvalidPlanNameError):
        fold([from_stored(_stored("PlanDefined", payload))])
