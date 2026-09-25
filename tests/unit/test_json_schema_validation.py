"""The two write-time checks of the schema-validated-values pattern.

One runs where a schema is declared, the other where values are carried.
The four-cell strict-versus-relaxed posture is the part worth pinning: each
cell is a deliberate answer to "no schema, some values", and three of the
four accept, so a test that only exercises the refusal proves little.
"""

import re
from typing import Any

import pytest

from keeper.shared.json_schema.subset import DRAFT_2020_12_URI
from keeper.shared.json_schema.validation import (
    ALLOWED_UNIT_SYSTEMS,
    validate_schema_declaration,
    validate_unit_annotations,
    validate_values_against_schema,
)

pytestmark = pytest.mark.unit


class _RefusedError(ValueError):
    """Stands in for the per-BC error class every caller passes."""


_SCHEMA: dict[str, Any] = {
    "$schema": DRAFT_2020_12_URI,
    "type": "object",
    "properties": {
        "energy": {"type": "number", "unit": {"system": "udunits", "code": "keV"}},
    },
}


def _declare(schema: dict[str, Any]) -> None:
    validate_schema_declaration(schema, error_class=_RefusedError)


def test_validate_schema_declaration_accepts_a_well_formed_subset_schema() -> None:
    _declare(_SCHEMA)


@pytest.mark.parametrize(
    "declared",
    [
        None,
        "http://json-schema.org/draft-07/schema#",
        "https://json-schema.org/draft/2019-09/schema",
    ],
)
def test_validate_schema_declaration_refuses_any_draft_but_2020_12(declared: str | None) -> None:
    schema: dict[str, Any] = {"type": "object"}
    if declared is not None:
        schema["$schema"] = declared
    with pytest.raises(_RefusedError, match="must be exactly"):
        _declare(schema)


def test_validate_schema_declaration_refuses_a_keyword_outside_the_subset() -> None:
    with pytest.raises(_RefusedError):
        _declare({"$schema": DRAFT_2020_12_URI, "oneOf": [{"type": "string"}]})


def test_validate_schema_declaration_refuses_a_pattern_that_is_not_a_valid_regex() -> None:
    """jsonschema-rs is the last gate; an unparseable pattern would fail at use time."""
    schema = {
        "$schema": DRAFT_2020_12_URI,
        "type": "object",
        "properties": {"s": {"type": "string", "pattern": "["}},
    }
    with pytest.raises(_RefusedError, match="rejected the schema"):
        _declare(schema)


def test_validate_unit_annotations_accepts_every_allowed_system() -> None:
    """Guards the allowlist: a system quietly dropped from it would not fail below."""
    for system in ALLOWED_UNIT_SYSTEMS:
        validate_unit_annotations(
            {"properties": {"v": {"unit": {"system": system, "code": "x"}}}},
            path="<root>",
            error_class=_RefusedError,
        )


@pytest.mark.parametrize(
    ("unit", "reason"),
    [
        ("not-a-dict", "the annotation must be an object"),
        ({"code": "keV"}, "system is required"),
        ({"system": "udunits"}, "code is required"),
        ({"system": "udunits", "code": "keV", "extra": 1}, "no unrecognised keys"),
        ({"system": "nope", "code": "keV"}, "system must be an allowed namespace"),
        ({"system": "udunits", "code": ""}, "code must be non-empty"),
        ({"system": "udunits", "code": "keV", "label": 5}, "label must be a string"),
    ],
)
def test_validate_unit_annotations_refuses_a_malformed_annotation(unit: Any, reason: str) -> None:
    with pytest.raises(_RefusedError):
        validate_unit_annotations(
            {"properties": {"v": {"unit": unit}}}, path="<root>", error_class=_RefusedError
        )


def test_validate_schema_declaration_refuses_a_malformed_unit_through_the_front_door() -> None:
    """The annotation check has to be wired INTO the declaration check.

    Every other unit test here calls `validate_unit_annotations` directly, so
    deleting its call site inside `validate_schema_declaration` left them all
    green. This is the test that notices.
    """
    schema = {
        "$schema": DRAFT_2020_12_URI,
        "type": "object",
        "properties": {"e": {"type": "number", "unit": {"system": "nope", "code": "keV"}}},
    }
    with pytest.raises(_RefusedError, match="allowed"):
        _declare(schema)


def test_validate_unit_annotations_recurses_into_a_nested_property() -> None:
    nested = {"properties": {"a": {"properties": {"b": {"unit": {"system": "nope", "code": "x"}}}}}}
    with pytest.raises(_RefusedError):
        validate_unit_annotations(nested, path="<root>", error_class=_RefusedError)


def test_validate_values_against_schema_accepts_conforming_values() -> None:
    validate_values_against_schema({"energy": 8.0}, _SCHEMA, error_class=_RefusedError)


def test_validate_values_against_schema_refuses_a_value_of_the_wrong_type() -> None:
    with pytest.raises(_RefusedError, match="validation failed at energy"):
        validate_values_against_schema({"energy": "hot"}, _SCHEMA, error_class=_RefusedError)


def test_strict_posture_refuses_values_when_no_schema_was_declared() -> None:
    with pytest.raises(_RefusedError, match="'a', 'b'"):
        validate_values_against_schema(
            {"b": 1, "a": 2},
            None,
            error_class=_RefusedError,
            no_schema_message="undeclared: {keys}",
        )


def test_relaxed_posture_accepts_values_when_no_schema_was_declared() -> None:
    """Omitting the message is how a caller says schemaless is acceptable here."""
    validate_values_against_schema({"a": 1}, None, error_class=_RefusedError)


def test_no_schema_and_no_values_is_accepted_under_the_strict_posture() -> None:
    validate_values_against_schema(
        {}, None, error_class=_RefusedError, no_schema_message="undeclared: {keys}"
    )


def test_a_schema_with_no_values_is_accepted_because_required_applies_later() -> None:
    validate_values_against_schema({}, _SCHEMA, error_class=_RefusedError)


def test_a_no_schema_message_without_the_keys_placeholder_is_a_caller_bug() -> None:
    """`str.format` ignores an unused keyword, so the omission is otherwise silent."""
    with pytest.raises(
        ValueError, match=re.escape("must contain a '{keys}' placeholder")
    ) as caught:
        validate_values_against_schema(
            {"a": 1}, None, error_class=_RefusedError, no_schema_message="no placeholder"
        )
    assert not isinstance(caught.value, _RefusedError), "a caller bug is not a validation failure"
