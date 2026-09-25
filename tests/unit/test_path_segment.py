"""One path segment, checked identically on the side that sends and the side that acts.

The refusals are the point. Each one below is a way a caller could name
something other than the single ordinary entry it meant to name.
"""

import pytest

from keeper.shared.path_segment import MAX_PATH_SEGMENT_LENGTH, is_safe_path_segment

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("segment", "reason"),
    [
        ("", "empty names nothing"),
        (".", "the directory itself"),
        ("..", "the parent directory"),
        ("a/b", "a forward separator splits it in two"),
        ("a\\b", "a backslash separator, refused on POSIX too"),
        ("a\0b", "a NUL truncates the name in C"),
        (" a", "leading whitespace names a different entry"),
        ("a ", "trailing whitespace names a different entry"),
        ("x" * (MAX_PATH_SEGMENT_LENGTH + 1), "one over what a filesystem can store"),
    ],
)
def test_is_safe_path_segment_refuses_a_segment_that_is_not_one_ordinary_entry(
    segment: str, reason: str
) -> None:
    assert not is_safe_path_segment(segment), reason


@pytest.mark.parametrize(
    "segment",
    ["scan_005.h5", "a.b.c", "-leading-dash", "...", "x" * MAX_PATH_SEGMENT_LENGTH],
)
def test_is_safe_path_segment_accepts_an_ordinary_entry_name(segment: str) -> None:
    assert is_safe_path_segment(segment)


def test_is_safe_path_segment_accepts_the_longest_storable_name() -> None:
    """The bound is inclusive, so a name at exactly the limit still names a real entry."""
    assert is_safe_path_segment("x" * MAX_PATH_SEGMENT_LENGTH)
    assert not is_safe_path_segment("x" * (MAX_PATH_SEGMENT_LENGTH + 1))


def test_is_safe_path_segment_refuses_rather_than_trims_surrounding_whitespace() -> None:
    """Trimming would answer a question the caller did not ask, about a different file."""
    assert not is_safe_path_segment(" scan.h5 ")
    assert is_safe_path_segment("scan.h5")
