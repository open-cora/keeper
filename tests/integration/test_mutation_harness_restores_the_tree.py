"""The harness puts the tree back, against a real git.

Marked integration rather than unit because it drives a real `git` in a
real repository, and the unit tier is pure by definition. The external
program here is git rather than Postgres, so no database fixture is
requested and no container starts.

Real git rather than a stand-in, deliberately. The two failures this
guards against were both git behaving exactly as documented while the
caller believed otherwise: `git checkout -- .` does not restore an
untracked file, and it is scoped to the current directory. A fake git
would have been written from the same wrong belief and agreed with it.

The test command is a stand-in, because what is under test is the
sequence around it, not pytest. A two-line script that prints a FAILED
line, or exits 0, or exits 5, produces every verdict the harness has to
tell apart, in milliseconds and with nothing nested.
"""

import subprocess
import sys
from pathlib import Path

import pytest

from tests._mutation.harness import CAUGHT, ERROR, SURVIVED, Result, run_mutation

pytestmark = [pytest.mark.integration]

_RED = [sys.executable, "-c", "import sys; print('FAILED tests/x.py::test_y'); sys.exit(1)"]
_GREEN = [sys.executable, "-c", "import sys; sys.exit(0)"]


def _git(root: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True, check=True
    )
    return done.stdout


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A throwaway repository with one committed file and a clean tree."""
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "harness@example.invalid")
    _git(root, "config", "user.name", "Harness")
    (root / "calc.py").write_text("VALUE = 1\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "initial", "--no-verify")
    return root


def _run(repo: Path, edit: str | None, command: list[str]) -> Result:
    return run_mutation(edit, ["ignored"], repo_root=repo, work_dir=repo, test_command=command)


def test_a_tree_with_an_unstaged_edit_is_refused_before_any_test_runs(repo: Path) -> None:
    """Refusing early is the whole basis for trusting the restore later."""
    (repo / "calc.py").write_text("VALUE = 2\n", encoding="utf-8")

    result = _run(repo, "true", _RED)
    assert result.outcome == ERROR
    assert "not fully staged" in result.detail


def test_an_untracked_file_in_the_tree_is_refused_before_any_test_runs(repo: Path) -> None:
    """The exact state that broke a real run: a new file git would not restore."""
    (repo / "stray.py").write_text("x = 1\n", encoding="utf-8")

    result = _run(repo, "true", _RED)
    assert result.outcome == ERROR
    assert "not fully staged" in result.detail


def test_an_edit_that_matches_nothing_is_reported_rather_than_run(repo: Path) -> None:
    """A sed that hits nothing would otherwise read as a gap in the tests."""
    result = _run(repo, "perl -pi -e 's/NOTHING_MATCHES_THIS/x/' calc.py", _RED)
    assert result.outcome == ERROR
    assert "changed nothing" in result.detail


def test_a_caught_mutation_leaves_the_file_exactly_as_it_was(repo: Path) -> None:
    result = _run(repo, "perl -pi -e 's/VALUE = 1/VALUE = 99/' calc.py", _RED)

    assert result.outcome == CAUGHT
    assert (repo / "calc.py").read_text(encoding="utf-8") == "VALUE = 1\n"
    assert _git(repo, "status", "--porcelain") == ""


def test_a_surviving_mutation_leaves_the_file_exactly_as_it_was(repo: Path) -> None:
    result = _run(repo, "perl -pi -e 's/VALUE = 1/VALUE = 99/' calc.py", _GREEN)

    assert result.outcome == SURVIVED
    assert (repo / "calc.py").read_text(encoding="utf-8") == "VALUE = 1\n"
    assert _git(repo, "status", "--porcelain") == ""


def test_a_mutation_that_creates_a_file_leaves_no_trace_behind(repo: Path) -> None:
    """The untracked case, from the other side.

    `git checkout` restores what is in the index and knows nothing about
    a file the edit invented. Left behind, it is untracked, so the next
    run's staged-tree check refuses to start and the batch stops for a
    reason that has nothing to do with the code under test.
    """
    result = _run(repo, "mkdir -p probe && echo 'y = 2' > probe/new.py", _RED)

    assert result.outcome == CAUGHT
    assert not (repo / "probe").exists()
    assert _git(repo, "status", "--porcelain") == ""


def test_a_baseline_run_reports_survived_on_an_untouched_tree(repo: Path) -> None:
    """Proof the tool can say SURVIVED, which a batch of catches cannot give."""
    result = _run(repo, None, _GREEN)

    assert result.outcome == SURVIVED
    assert _git(repo, "status", "--porcelain") == ""


def test_an_edit_that_stages_itself_is_reported_as_an_unrestorable_tree(repo: Path) -> None:
    """The last line of defence, exercised.

    Every other test here leaves a restore that works, so none of them
    would notice the post-restore check being deleted. An edit that
    stages its own change defeats the restore honestly: `git checkout`
    puts back what the index holds, and the index now holds the
    mutation. The harness has to say so and stop the batch, because a
    verdict after this point is measuring the previous mutation.
    """
    result = _run(repo, "perl -pi -e 's/VALUE = 1/VALUE = 99/' calc.py && git add -A", _RED)

    assert result.outcome == ERROR
    assert "did not restore" in result.detail
    assert (repo / "calc.py").read_text(encoding="utf-8") == "VALUE = 99\n"
