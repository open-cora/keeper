"""Reading a finished test run, which is where one wrong answer came from.

Two pure functions decide what a mutation run concluded. Both were got
wrong in practice, in this repository, and both wrong answers looked
like results rather than like bugs.

Tables rather than one case each, because every row here is a shape that
actually occurred: pytest exiting 4 on a bad path, exiting 5 on a target
that collected nothing, and porcelain lines for the two different ways a
file can fail to be restorable.
"""

import pytest

from tests._mutation.harness import CAUGHT, ERROR, SURVIVED, unstaged, verdict

pytestmark = pytest.mark.unit

_STATUS_LINES: tuple[tuple[str, str, bool], ...] = (
    ("staged new", "A  new.py", True),
    ("staged edit", "M  edited.py", True),
    ("staged rename", "R  old.py -> new.py", True),
    ("edited but not added", " M edited.py", False),
    ("added then edited again", "MM edited.py", False),
    ("never added", "?? stray.py", False),
    ("deleted in the tree", " D gone.py", False),
)


@pytest.mark.parametrize(
    ("line", "restorable"),
    [(line, restorable) for _label, line, restorable in _STATUS_LINES],
    ids=[label for label, _line, _restorable in _STATUS_LINES],
)
def test_a_porcelain_line_is_restorable_only_when_its_second_column_is_blank(
    line: str, restorable: bool
) -> None:
    """Both untracked and unstaged have to be caught by the same rule.

    They fail differently and they fail for the same reason: git can
    restore from the index, and neither of these is in the index.
    """
    assert (unstaged(line) == []) is restorable


_RUNS: tuple[tuple[str, int, str, str], ...] = (
    ("a test failed", 1, "FAILED tests/x.py::test_thing\n1 failed", CAUGHT),
    ("everything passed", 0, "230 passed", SURVIVED),
    ("target collected nothing", 5, "no tests ran", ERROR),
    ("bad path", 4, "ERROR: file or directory not found: tests/a tests/b", ERROR),
    ("import blew up", 2, "INTERNALERROR> ImportError", ERROR),
    ("failed with no FAILED line", 1, "some other trouble", ERROR),
)


@pytest.mark.parametrize(
    ("returncode", "output", "expected"),
    [(code, output, expected) for _label, code, output, expected in _RUNS],
    ids=[label for label, _c, _o, _e in _RUNS],
)
def test_a_run_counts_as_caught_only_when_a_test_reported_failure(
    returncode: int, output: str, expected: str
) -> None:
    """Exit code alone cannot tell a failing test from a failing command.

    The bad-path row is the one that happened: two pytest targets passed
    as a single argument, exit 4, and a harness reading non-zero as a
    catch reported four mutations caught that had never been run.
    """
    assert verdict(returncode, output).outcome == expected


def test_a_caught_run_names_the_tests_that_failed() -> None:
    """The verdict carries which test objected, so a batch is readable."""
    result = verdict(1, "FAILED tests/x.py::test_alpha\nFAILED tests/y.py::test_beta\n2 failed")
    assert result.outcome == CAUGHT
    assert "test_alpha" in result.detail
    assert "test_beta" in result.detail


def test_a_target_that_collected_nothing_is_named_rather_than_left_as_an_exit_code() -> None:
    """The one failure that most resembles success gets its own words.

    Exit 5 already falls into the error branch on the strength of being
    non-zero, so asserting the outcome alone cannot tell the dedicated
    branch from its absence. That was measured: deleting the branch left
    every test here green. What is lost without it is the reader being
    told the run collected nothing, which is the difference between
    fixing a target path and hunting a bug that was never exercised.
    """
    result = verdict(5, "no tests ran in 0.01s")
    assert result.outcome == ERROR
    assert "collected no tests" in result.detail
