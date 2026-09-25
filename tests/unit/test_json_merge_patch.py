"""RFC 7396 merge semantics, plus the aliasing guarantee the docstring adds to them.

The aliasing half matters more than the merge half here. The returned dict
becomes an event payload, and an event payload that still points into the
caller's nested dicts can be mutated after it is recorded.
"""

from typing import Any

import pytest

from keeper.shared.json_merge_patch import merge_patch

pytestmark = pytest.mark.unit


def test_merge_patch_replaces_a_key_the_patch_names() -> None:
    assert merge_patch({"a": 1}, {"a": 2}) == {"a": 2}


def test_merge_patch_adds_a_key_the_current_document_lacks() -> None:
    assert merge_patch({"a": 1}, {"b": 2}) == {"a": 1, "b": 2}


def test_merge_patch_preserves_a_key_the_patch_does_not_name() -> None:
    assert merge_patch({"a": 1, "b": 2}, {"a": 9}) == {"a": 9, "b": 2}


def test_merge_patch_deletes_a_key_whose_patch_value_is_null() -> None:
    assert merge_patch({"a": 1, "b": 2}, {"b": None}) == {"a": 1}


def test_merge_patch_ignores_a_null_for_a_key_that_is_already_absent() -> None:
    assert merge_patch({"a": 1}, {"b": None}) == {"a": 1}


def test_merge_patch_merges_into_a_nested_object_rather_than_replacing_the_object() -> None:
    assert merge_patch({"a": {"x": 1, "y": 2}}, {"a": {"y": 3}}) == {"a": {"x": 1, "y": 3}}


def test_merge_patch_deletes_a_nested_key_whose_value_is_null() -> None:
    assert merge_patch({"a": {"x": 1, "y": 2}}, {"a": {"y": None}}) == {"a": {"x": 1}}


def test_merge_patch_replaces_a_scalar_with_an_object_without_recursing() -> None:
    """There is nothing to merge into, so the patch value wins whole."""
    assert merge_patch({"a": 1}, {"a": {"x": 2}}) == {"a": {"x": 2}}


def test_merge_patch_replaces_an_object_with_a_scalar() -> None:
    assert merge_patch({"a": {"x": 1}}, {"a": 5}) == {"a": 5}


def test_merge_patch_leaves_the_current_document_unmodified() -> None:
    current: dict[str, Any] = {"a": {"x": 1}}
    merge_patch(current, {"a": {"x": 2}})
    assert current == {"a": {"x": 1}}


def test_merge_patch_result_shares_no_nested_object_with_the_current_document() -> None:
    """Mutating the result must not reach back into what the caller passed in."""
    current: dict[str, Any] = {"a": {"x": 1}}
    result = merge_patch(current, {"b": 2})
    result["a"]["x"] = 99
    assert current == {"a": {"x": 1}}


def test_merge_patch_result_shares_no_nested_object_with_the_patch() -> None:
    """A caller that reuses its patch dict must not be able to edit a recorded payload."""
    patch: dict[str, Any] = {"a": {"x": 1}}
    result = merge_patch({}, patch)
    patch["a"]["x"] = 99
    assert result == {"a": {"x": 1}}


def test_merge_patch_with_an_empty_patch_returns_the_document_unchanged() -> None:
    assert merge_patch({"a": 1}, {}) == {"a": 1}
