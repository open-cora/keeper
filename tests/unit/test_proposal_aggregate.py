"""The Proposal aggregate: its two events, its fold, and the round trip.

Two events, so there is a state machine, and it has exactly one edge. The
properties worth pinning are that the edge is one way, that the parameters
survive the trip through the log as a document rather than as a shared
reference, and that open is a null reference rather than a stored flag.
"""

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest

from keeper.counsel.aggregates.proposal import (
    Proposal,
    ProposalMade,
    ProposalTaken,
    evolve,
    fold,
    from_stored,
    to_payload,
)
from keeper.infrastructure.ports.event_store import StoredEvent

pytestmark = pytest.mark.unit

_WHEN = datetime(2026, 9, 19, 14, 30, tzinfo=UTC)
_PARAMETERS: dict[str, Any] = {"exposure_time_s": 0.1, "num_projections": 1500}


def _made(**overrides: object) -> ProposalMade:
    fields: dict[str, object] = {
        "proposal_id": uuid4(),
        "actor_id": uuid4(),
        "plan_id": uuid4(),
        "parameters": dict(_PARAMETERS),
        "occurred_at": _WHEN,
    }
    fields.update(overrides)
    return ProposalMade(**fields)  # pyright: ignore[reportArgumentType]


def _taken(proposal_id: object, **overrides: object) -> ProposalTaken:
    fields: dict[str, object] = {
        "proposal_id": proposal_id,
        "execution_id": uuid4(),
        "step_id": uuid4(),
        "occurred_at": _WHEN,
    }
    fields.update(overrides)
    return ProposalTaken(**fields)  # pyright: ignore[reportArgumentType]


def _stored(event: ProposalMade | ProposalTaken) -> StoredEvent:
    return StoredEvent(
        position=1,
        event_id=uuid4(),
        stream_type="Proposal",
        stream_id=event.proposal_id,
        version=1,
        event_type=type(event).__name__,
        schema_version=1,
        payload=to_payload(event),
        correlation_id=uuid4(),
        causation_id=None,
        occurred_at=event.occurred_at,
        recorded_at=event.occurred_at,
    )


def test_folding_an_empty_stream_gives_nothing() -> None:
    assert fold([]) is None


def test_folding_a_genesis_gives_a_proposal_with_no_acquisition() -> None:
    made = _made()

    state = fold([made])

    assert state == Proposal(
        id=made.proposal_id,
        actor_id=made.actor_id,
        plan_id=made.plan_id,
        parameters=_PARAMETERS,
        execution_id=None,
        step_id=None,
    )


def test_a_proposal_with_no_acquisition_reads_as_not_taken() -> None:
    assert fold([_made()]).is_taken is False  # pyright: ignore[reportOptionalMemberAccess]


def test_folding_a_take_records_the_acquisition_and_makes_it_taken() -> None:
    """Both halves land, because one without the other names nothing.

    A step is an entity inside an execution rather than a stream of its
    own, so a fold that kept the step and dropped the root would leave a
    reference no reader can follow.
    """
    made = _made()
    execution_id = uuid4()
    step_id = uuid4()

    state = fold(
        [
            made,
            ProposalTaken(
                proposal_id=made.proposal_id,
                execution_id=execution_id,
                step_id=step_id,
                occurred_at=_WHEN,
            ),
        ]
    )

    assert state is not None
    assert (state.execution_id, state.step_id) == (execution_id, step_id)
    assert state.is_taken is True


def test_taking_leaves_every_other_field_unchanged() -> None:
    made = _made()

    state = fold([made, _taken(made.proposal_id)])

    assert state is not None
    assert (state.id, state.actor_id, state.plan_id) == (
        made.proposal_id,
        made.actor_id,
        made.plan_id,
    )
    assert state.parameters == _PARAMETERS


def test_taking_before_a_genesis_is_a_broken_stream() -> None:
    with pytest.raises(ValueError, match="ProposalTaken"):
        evolve(None, _taken(uuid4()))


def test_the_state_does_not_alias_the_parameters_the_event_carries() -> None:
    """A dict on a payload is shallow-copied into state, never shared.

    The fitness test that pins immutable collections cannot reach a
    freeform document, so this is the companion defence
    docs/reference/modeling.md asks for, tested rather than asserted.
    """
    made = _made()

    state = fold([made])

    assert state is not None
    state.parameters["exposure_time_s"] = 99.0
    assert made.parameters["exposure_time_s"] == 0.1


def test_a_genesis_survives_the_round_trip_through_the_log() -> None:
    made = _made()

    assert from_stored(_stored(made)) == made


def test_a_take_survives_the_round_trip_through_the_log() -> None:
    taken = _taken(uuid4())

    assert from_stored(_stored(taken)) == taken


def test_an_unknown_event_type_on_this_stream_is_refused() -> None:
    stored = _stored(_made())
    unknown = StoredEvent(
        position=stored.position,
        event_id=stored.event_id,
        stream_type=stored.stream_type,
        stream_id=stored.stream_id,
        version=stored.version,
        event_type="ProposalWithdrawn",
        schema_version=stored.schema_version,
        payload=stored.payload,
        correlation_id=stored.correlation_id,
        causation_id=stored.causation_id,
        occurred_at=stored.occurred_at,
        recorded_at=stored.recorded_at,
    )

    with pytest.raises(ValueError, match="Unknown Proposal event_type"):
        from_stored(unknown)


def test_a_malformed_payload_names_the_event_and_not_the_field() -> None:
    stored = _stored(_made())
    broken = StoredEvent(
        position=stored.position,
        event_id=stored.event_id,
        stream_type=stored.stream_type,
        stream_id=stored.stream_id,
        version=stored.version,
        event_type="ProposalMade",
        schema_version=stored.schema_version,
        payload={**stored.payload, "plan_id": "not-a-uuid"},
        correlation_id=stored.correlation_id,
        causation_id=stored.causation_id,
        occurred_at=stored.occurred_at,
        recorded_at=stored.recorded_at,
    )

    with pytest.raises(ValueError, match="Malformed ProposalMade"):
        from_stored(broken)
