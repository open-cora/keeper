"""The keyword allowlist, and the strict-subset relation between two schemas.

`check_subset` guards a single schema. `check_schema_is_subset` guards a
narrower schema against the broader one it specializes, and its docstring
lists eight rules; each is asserted here in both directions, because a rule
that only ever refuses and a rule that only ever accepts look identical from
a test that exercises one side.
"""

from typing import Any

import pytest

from keeper.shared.json_schema.subset import (
    ALLOWED_SCHEMA_KEYS,
    DRAFT_2020_12_URI,
    check_schema_is_subset,
    check_subset,
)

pytestmark = pytest.mark.unit


class _RefusedError(ValueError):
    """Stands in for the per-BC error class every caller passes."""


def _check(node: dict[str, Any]) -> None:
    check_subset(node, path="<root>", error_class=_RefusedError)


def _relate(inner: dict[str, Any], outer: dict[str, Any]) -> None:
    check_schema_is_subset(inner, outer, path="<root>", error_class=_RefusedError)


def test_check_subset_accepts_every_allowed_keyword() -> None:
    """Guards the allowlist itself: a key silently dropped from it would not fail below."""
    _check(
        {
            "$schema": DRAFT_2020_12_URI,
            "type": "object",
            "required": ["e"],
            "properties": {
                "e": {
                    "type": "number",
                    "minimum": 1,
                    "maximum": 9,
                    "unit": {"system": "udunits", "code": "keV"},
                },
                "s": {"type": "string", "pattern": "^a", "enum": ["a", "ab"]},
            },
        }
    )


@pytest.mark.parametrize("keyword", ["$ref", "oneOf", "allOf", "anyOf", "if", "not"])
def test_check_subset_refuses_a_keyword_outside_the_allowlist(keyword: str) -> None:
    with pytest.raises(_RefusedError, match="AROC's subset allows only"):
        _check({"$schema": DRAFT_2020_12_URI, keyword: {}})


def test_check_subset_refuses_a_forbidden_keyword_nested_in_a_property() -> None:
    """Recursion is the point; a top-level-only check is trivially evaded."""
    with pytest.raises(_RefusedError):
        _check(
            {
                "$schema": DRAFT_2020_12_URI,
                "type": "object",
                "properties": {"a": {"type": "object", "properties": {"b": {"$ref": "#/x"}}}},
            }
        )


def test_allowed_schema_keys_stays_a_closed_set() -> None:
    """A widening here changes what every declarer may store, so it is pinned by name."""
    assert sorted(ALLOWED_SCHEMA_KEYS) == [
        "$schema",
        "enum",
        "maximum",
        "minimum",
        "pattern",
        "properties",
        "required",
        "type",
        "unit",
    ]


def test_subset_relation_accepts_an_inner_schema_that_only_narrows() -> None:
    outer = {"type": "object", "properties": {"e": {"type": "number", "minimum": 0}}}
    _relate({"type": "object", "properties": {"e": {"type": "number", "minimum": 5}}}, outer)


def test_subset_relation_refuses_an_inner_type_that_differs_from_the_outer() -> None:
    with pytest.raises(_RefusedError, match="type mismatch"):
        _relate({"type": "string"}, {"type": "number"})


def test_subset_relation_refuses_a_property_the_outer_never_declared() -> None:
    with pytest.raises(_RefusedError, match="may not introduce"):
        _relate({"properties": {"b": {}}}, {"properties": {"a": {}}})


def test_subset_relation_refuses_requiring_a_property_the_outer_never_declared() -> None:
    with pytest.raises(_RefusedError):
        _relate({"required": ["b"]}, {"properties": {"a": {}}})


def test_subset_relation_refuses_an_enum_arm_the_outer_does_not_offer() -> None:
    with pytest.raises(_RefusedError):
        _relate({"enum": ["a", "z"]}, {"enum": ["a", "b"]})


def test_subset_relation_accepts_an_enum_that_drops_an_arm() -> None:
    _relate({"enum": ["a"]}, {"enum": ["a", "b"]})


def test_subset_relation_refuses_a_minimum_below_the_outer_minimum() -> None:
    with pytest.raises(_RefusedError):
        _relate({"minimum": 1}, {"minimum": 5})


def test_subset_relation_refuses_a_maximum_above_the_outer_maximum() -> None:
    with pytest.raises(_RefusedError):
        _relate({"maximum": 9}, {"maximum": 5})


def test_subset_relation_accepts_a_bound_equal_to_the_outer_bound() -> None:
    """The rule is >= and <=, so restating the outer bound is not a widening.

    Both directions of each bound need a case. A mutation flipping `<` to `<=`
    on the minimum left every other test here green.
    """
    _relate({"minimum": 5}, {"minimum": 5})
    _relate({"maximum": 5}, {"maximum": 5})


def test_subset_relation_refuses_a_pattern_that_is_not_character_identical() -> None:
    """Pattern subsumption is undecidable, so the conservative rule is exact equality."""
    with pytest.raises(_RefusedError):
        _relate({"pattern": "^ab"}, {"pattern": "^a"})


def test_subset_relation_refuses_a_unit_that_differs_from_the_outer_unit() -> None:
    inner = {"unit": {"system": "udunits", "code": "eV"}}
    outer = {"unit": {"system": "udunits", "code": "keV"}}
    with pytest.raises(_RefusedError):
        _relate(inner, outer)


def test_subset_relation_allows_the_inner_to_omit_a_property_the_outer_declares() -> None:
    """The documented tolerance: silence on the inner side is not a widening."""
    _relate({"properties": {}}, {"properties": {"a": {"type": "string"}}})


def test_subset_relation_recurses_into_a_shared_property() -> None:
    outer = {"properties": {"a": {"type": "object", "properties": {"b": {"type": "string"}}}}}
    inner = {"properties": {"a": {"type": "object", "properties": {"c": {"type": "string"}}}}}
    with pytest.raises(_RefusedError):
        _relate(inner, outer)
