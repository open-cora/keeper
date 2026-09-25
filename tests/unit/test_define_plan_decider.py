"""The decision that defining a plan produces.

Two refusals carry the file. A name has to be a name, and a schema has
to be one this system will still be able to read back in five years,
which is what the constrained subset is for. Everything a plan can
refuse, it refuses here, because the decider is the only place both
surfaces pass through.
"""

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest

from keeper.execution.aggregates.plan import (
    PLAN_NAME_MAX_LENGTH,
    InvalidPlanNameError,
    InvalidPlanParametersSchemaError,
    Plan,
    PlanAlreadyExistsError,
    PlanDefined,
    PlanName,
)
from keeper.execution.features.define_plan import DefinePlan, decide

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 9, 18, 9, 30, tzinfo=UTC)

_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {"exposure_seconds": {"type": "number", "minimum": 0}},
    "required": ["exposure_seconds"],
}
"""A schema inside the subset this system stores.

Nine keywords are allowed and this uses four of them. Notably absent are
`additionalProperties` and `unevaluatedProperties`, which the authoring
discipline in docs/reference/conventions.md tells an author to set and
which `keeper.shared.json_schema.subset` refuses. The code is what runs, so
this schema follows the code.
"""


def test_defining_a_plan_emits_one_event_carrying_the_name_and_the_schema() -> None:
    new_id = uuid4()

    events = decide(
        None,
        DefinePlan(name="count", parameters_schema=_SCHEMA),
        now=_NOW,
        new_id=new_id,
    )

    assert events == [
        PlanDefined(
            plan_id=new_id,
            plan_name="count",
            parameters_schema=_SCHEMA,
            occurred_at=_NOW,
        )
    ]


def test_the_emitted_name_is_the_trimmed_one() -> None:
    """The value object runs on the way in, not only on the way out.

    A decider that passed the command's string through would put an
    untrimmed name on an append-only row, and the fold would then trim
    it on every read. The stored value and the folded value would differ
    forever, and nothing downstream reading the payload would agree with
    anything reading the state.
    """
    events = decide(
        None,
        DefinePlan(name="  count  ", parameters_schema=_SCHEMA),
        now=_NOW,
        new_id=uuid4(),
    )

    assert events[0].plan_name == "count"


def test_defining_a_plan_on_a_live_stream_is_refused() -> None:
    existing = Plan(id=uuid4(), name=PlanName("count"), parameters_schema=_SCHEMA)

    with pytest.raises(PlanAlreadyExistsError):
        decide(
            existing,
            DefinePlan(name="count", parameters_schema=_SCHEMA),
            now=_NOW,
            new_id=uuid4(),
        )


def test_defining_a_plan_with_a_blank_name_is_refused() -> None:
    with pytest.raises(InvalidPlanNameError):
        decide(
            None,
            DefinePlan(name="   ", parameters_schema=_SCHEMA),
            now=_NOW,
            new_id=uuid4(),
        )


def test_defining_a_plan_with_an_over_long_name_is_refused() -> None:
    with pytest.raises(InvalidPlanNameError):
        decide(
            None,
            DefinePlan(name="x" * (PLAN_NAME_MAX_LENGTH + 1), parameters_schema=_SCHEMA),
            now=_NOW,
            new_id=uuid4(),
        )


def test_defining_a_plan_whose_schema_declares_no_draft_is_refused() -> None:
    """The draft is pinned, so a schema that does not say which one is not one.

    An unpinned document is read by whatever the validator happens to
    default to, which is a different reading in a different year. The
    plan would go on looking valid while the parameters it accepts
    quietly changed.
    """
    with pytest.raises(InvalidPlanParametersSchemaError, match="2020-12"):
        decide(
            None,
            DefinePlan(name="count", parameters_schema={"type": "object"}),
            now=_NOW,
            new_id=uuid4(),
        )


def test_defining_a_plan_whose_schema_uses_a_forbidden_keyword_is_refused() -> None:
    """`$ref` is outside the subset, and the refusal is the point.

    The subset is what lets a stored schema be replayed and rebuilt
    without resolving anything. A reference is a promise that something
    else will still be reachable, which is not a promise an append-only
    row can keep.
    """
    with_a_reference = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": {"detector": {"$ref": "#/$defs/detector"}},
    }

    with pytest.raises(InvalidPlanParametersSchemaError):
        decide(
            None,
            DefinePlan(name="count", parameters_schema=with_a_reference),
            now=_NOW,
            new_id=uuid4(),
        )


def test_defining_a_plan_that_constrains_nothing_is_accepted() -> None:
    """Declaring no constraints is allowed; declaring no schema is not.

    The distinction is the whole reason the schema is required here. An
    operator with nothing to constrain says so in the record, and a
    reader can tell that from an operator who never got round to it.
    """
    constrains_nothing = {"$schema": "https://json-schema.org/draft/2020-12/schema"}

    events = decide(
        None,
        DefinePlan(name="count", parameters_schema=constrains_nothing),
        now=_NOW,
        new_id=uuid4(),
    )

    assert events[0].parameters_schema == constrains_nothing
