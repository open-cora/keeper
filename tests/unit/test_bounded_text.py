"""The bounded-text helper and the decorator that installs it on a value object.

`bounded_name` is the part worth pinning. It replaces the `__init__` that
`@dataclass` synthesized, which is the kind of change that silently costs a
class its equality, its hash or its pattern-matching support. Its docstring
promises all of those survive, so each is asserted here rather than trusted.
"""

from dataclasses import dataclass

import pytest

from keeper.shared.bounded_text import bounded_name, validate_bounded_text

pytestmark = pytest.mark.unit


class _RefusedError(Exception):
    """Stands in for the per-aggregate error class a real value object passes."""


@bounded_name(max_length=8, error_class=_RefusedError)
@dataclass(frozen=True)
class _Name:
    value: str


def test_validate_bounded_text_returns_the_trimmed_value() -> None:
    assert validate_bounded_text("  hi  ", max_length=5, error_class=_RefusedError) == "hi"


def test_validate_bounded_text_refuses_a_string_that_is_only_whitespace() -> None:
    with pytest.raises(_RefusedError):
        validate_bounded_text("   ", max_length=5, error_class=_RefusedError)


def test_validate_bounded_text_measures_length_after_trimming() -> None:
    """Five characters inside padding fit a bound of five; the padding is not content."""
    assert validate_bounded_text("  abcde  ", max_length=5, error_class=_RefusedError) == "abcde"


def test_validate_bounded_text_refuses_one_character_over_the_bound() -> None:
    with pytest.raises(_RefusedError):
        validate_bounded_text("abcdef", max_length=5, error_class=_RefusedError)


def test_validate_bounded_text_reports_the_untrimmed_value_it_was_given() -> None:
    """The caller needs the original to see that whitespace was the problem."""
    with pytest.raises(_RefusedError) as caught:
        validate_bounded_text("   ", max_length=5, error_class=_RefusedError)
    assert caught.value.args[0] == "   "


def test_bounded_name_stores_the_trimmed_value_on_the_instance() -> None:
    assert _Name("  ab  ").value == "ab"


def test_bounded_name_refuses_a_whitespace_only_value() -> None:
    with pytest.raises(_RefusedError):
        _Name("   ")


def test_bounded_name_refuses_a_value_over_the_bound() -> None:
    with pytest.raises(_RefusedError):
        _Name("x" * 9)


def test_bounded_name_leaves_equality_comparing_by_value() -> None:
    assert _Name("a") == _Name("a")
    assert _Name("a") != _Name("b")


def test_bounded_name_leaves_the_instance_hashable() -> None:
    """A value object that stops hashing cannot go in a set or a dict key."""
    assert len({_Name("a"), _Name("a"), _Name("b")}) == 2


def test_bounded_name_leaves_the_dataclass_repr_intact() -> None:
    assert repr(_Name("a")) == "_Name(value='a')"


def test_bounded_name_leaves_positional_pattern_matching_working() -> None:
    match _Name("ab"):
        case _Name("ab"):
            matched = True
        case _:
            matched = False
    assert matched


def test_bounded_name_refuses_a_class_that_is_not_a_dataclass() -> None:
    """Applied under `@dataclass` instead of above it, there is no `__init__` to wrap."""
    with pytest.raises(TypeError, match="above @dataclass"):
        bounded_name(max_length=4, error_class=_RefusedError)(type("_Plain", (), {}))


def test_bounded_name_refuses_a_dataclass_without_a_value_field() -> None:
    @dataclass(frozen=True)
    class _NoValue:
        label: str

    with pytest.raises(TypeError, match="`value` field"):
        bounded_name(max_length=4, error_class=_RefusedError)(_NoValue)
