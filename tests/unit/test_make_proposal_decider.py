"""The decision that making a proposal produces.

Two invariants, and the second is what makes this a proposal rather than
a wish: values that could not be run are refused at the moment they are
advised. The proposer is the other thing worth pinning, because it
arrives as a parameter rather than on the command and a decider that
read it off the command would compile.
"""

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest

from keeper.counsel.aggregates.proposal import (
    InvalidProposalParametersError,
    Proposal,
    ProposalAlreadyExistsError,
    ProposalMade,
)
from keeper.counsel.features.make_proposal import (
    MakeProposal,
    MakeProposalContext,
    decide,
)
from keeper.execution.aggregates.plan import Plan, PlanName

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 9, 19, 14, 30, tzinfo=UTC)
_OPEN_SCHEMA: dict[str, Any] = {"$schema": "https://json-schema.org/draft/2020-12/schema"}
_TYPED_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {"exposure_time_s": {"type": "number"}},
    "required": ["exposure_time_s"],
}


def _context(schema: dict[str, Any]) -> MakeProposalContext:
    return MakeProposalContext(
        plan=Plan(id=uuid4(), name=PlanName("count"), parameters_schema=schema)
    )


def test_proposing_on_an_empty_stream_emits_one_event() -> None:
    plan_id, actor_id, new_id = uuid4(), uuid4(), uuid4()

    events = decide(
        None,
        MakeProposal(plan_id=plan_id, parameters={"exposure_time_s": 0.1}),
        context=_context(_TYPED_SCHEMA),
        actor_id=actor_id,
        now=_NOW,
        new_id=new_id,
    )

    assert events == [
        ProposalMade(
            proposal_id=new_id,
            actor_id=actor_id,
            plan_id=plan_id,
            parameters={"exposure_time_s": 0.1},
            occurred_at=_NOW,
        )
    ]


def test_the_proposer_comes_from_the_parameter_and_not_from_the_command() -> None:
    """A caller cannot advise as somebody else, because it cannot say who it is."""
    actor_id = uuid4()

    events = decide(
        None,
        MakeProposal(plan_id=uuid4(), parameters={}),
        context=_context(_OPEN_SCHEMA),
        actor_id=actor_id,
        now=_NOW,
        new_id=uuid4(),
    )

    assert events[0].actor_id == actor_id


def test_proposing_onto_a_live_stream_is_refused() -> None:
    existing = Proposal(id=uuid4(), actor_id=uuid4(), plan_id=uuid4(), parameters={})

    with pytest.raises(ProposalAlreadyExistsError):
        decide(
            existing,
            MakeProposal(plan_id=uuid4(), parameters={}),
            context=_context(_OPEN_SCHEMA),
            actor_id=uuid4(),
            now=_NOW,
            new_id=uuid4(),
        )


def test_values_the_plans_schema_refuses_are_refused_here() -> None:
    with pytest.raises(InvalidProposalParametersError):
        decide(
            None,
            MakeProposal(plan_id=uuid4(), parameters={"exposure_time_s": "half a second"}),
            context=_context(_TYPED_SCHEMA),
            actor_id=uuid4(),
            now=_NOW,
            new_id=uuid4(),
        )


def test_sending_no_values_at_all_is_accepted_even_where_the_schema_requires_some() -> None:
    """The shared validator skips `required` when the values are empty.

    Documented behaviour rather than an oversight here: that helper
    defers `required` to the point where values are finally resolved and
    acted on. So a proposal naming a plan that requires an exposure time,
    and proposing nothing, is recorded. `define_procedure` has the same
    hole against the same validator, and closing it for one and not the
    other would make two rules out of one. Pinned so that a change to the
    shared posture shows up here rather than silently widening what a
    proposal may claim.
    """
    events = decide(
        None,
        MakeProposal(plan_id=uuid4(), parameters={}),
        context=_context(_TYPED_SCHEMA),
        actor_id=uuid4(),
        now=_NOW,
        new_id=uuid4(),
    )

    assert events[0].parameters == {}


def test_a_schema_that_constrains_nothing_accepts_anything() -> None:
    events = decide(
        None,
        MakeProposal(plan_id=uuid4(), parameters={"anything": [1, 2, 3]}),
        context=_context(_OPEN_SCHEMA),
        actor_id=uuid4(),
        now=_NOW,
        new_id=uuid4(),
    )

    assert events[0].parameters == {"anything": [1, 2, 3]}


def test_the_command_carries_no_reported_time_for_the_decision_to_use() -> None:
    """R8 as a property: proposing is authored here, so only `now` can date it."""
    assert "occurred_at" not in MakeProposal.__dataclass_fields__

    events = decide(
        None,
        MakeProposal(plan_id=uuid4(), parameters={}),
        context=_context(_OPEN_SCHEMA),
        actor_id=uuid4(),
        now=_NOW,
        new_id=uuid4(),
    )

    assert events[0].occurred_at == _NOW
