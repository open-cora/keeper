"""Run one mutation, report one verdict, and leave the tree as it was found.

A mutation run is an experiment, and the experiment is worthless unless
four things hold. Each of them broke at least once while this repository
was being built, each time silently, and each time the wrong answer was
noticed only because a number looked odd:

    1  the edit actually landed
       A sed that matched nothing reports "nothing caught it", which
       reads exactly like a gap in the tests.

    2  the restore actually restored
       `git checkout -- .` skips untracked files, and is scoped to the
       current directory. Both bit. The next mutation then runs on the
       previous one's damage and every verdict after that is fiction.

    3  red means a TEST failed
       A missing path, a broken import or a collection error all exit
       non-zero. Reading non-zero as "caught" turns a broken command
       line into a clean bill of health.

    4  the tool can say SURVIVED at all
       A harness that reports "caught" for everything, including an
       unmutated tree, is measuring nothing.

Requiring a fully staged tree up front is what makes 2 tractable.
Staged files are restorable from the index, untracked ones are not, so
the tool refuses to start rather than half-work. It also means anything
untracked after the edit was created BY the edit, which is what makes
removing it safe.

The check that matters most is the one after the restore: the tree must
match, exactly, what it looked like before. A baseline run at the start
of a batch proves only that things were fine before anything happened.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Final

CAUGHT: Final = "caught"
SURVIVED: Final = "SURVIVED"
ERROR: Final = "HARNESS ERROR"

DEFAULT_TEST_COMMAND: Final = ("uv", "run", "pytest", "-q", "-p", "no:randomly")


@dataclass(frozen=True)
class Result:
    """What one mutation produced, and why."""

    outcome: str
    detail: str

    def line(self, label: str) -> str:
        """The one-line report, aligned so a batch reads as a column."""
        return f"  {label:<52} {self.outcome:<14} {self.detail}".rstrip()


def unstaged(status: str) -> list[str]:
    """Porcelain lines that are not fully staged, untracked files included.

    Git's porcelain format is two status columns, the index then the
    working tree. A fully staged change leaves the second column blank,
    so one test covers both "edited but not added" and "never added":
    an untracked line is `??`, whose second column is a question mark.
    """
    return [line for line in status.splitlines() if line[1:2] != " "]


def verdict(returncode: int, output: str) -> Result:
    """Read a finished test run.

    Exit code alone cannot tell a failing test from a failing command,
    which is why a refusal needs a `FAILED` line and not merely a
    non-zero exit. Exit 5 is pytest's "collected nothing", the one that
    most resembles success and least resembles evidence.
    """
    if returncode == 5:
        return Result(ERROR, "the target collected no tests")
    failures = [line for line in output.splitlines() if line.startswith("FAILED")]
    if failures:
        named = " ".join(f.partition("::")[2] or f for f in failures[:2])
        return Result(CAUGHT, named)
    if returncode == 0:
        return Result(SURVIVED, "")
    last = next((line for line in reversed(output.splitlines()) if line.strip()), "")
    return Result(ERROR, f"exit {returncode}, no FAILED line :: {last[:90]}")


def _git(repo_root: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", "-C", str(repo_root), *args], capture_output=True, text=True, check=False
    )
    return done.stdout


def _status(repo_root: Path) -> str:
    return _git(repo_root, "status", "--porcelain")


def run_mutation(
    edit: str | None,
    targets: list[str],
    *,
    repo_root: Path,
    work_dir: Path,
    test_command: list[str],
) -> Result:
    """Apply one edit, run the tests, restore, and verify the restore.

    `edit` of None runs the tests against an untouched tree, which is
    the baseline: it proves the target is green and that this tool is
    able to report SURVIVED rather than only ever reporting a catch.
    """
    before = _status(repo_root)
    if dirty := unstaged(before):
        return Result(
            ERROR,
            f"tree is not fully staged ({len(dirty)} path(s), first: {dirty[0][:40]!r}). "
            "Stage everything first: only staged files can be restored.",
        )

    if edit is not None:
        subprocess.run(edit, shell=True, cwd=repo_root, check=False)
        if _status(repo_root) == before:
            return Result(ERROR, "the edit changed nothing, so the run proves nothing")

    done = subprocess.run(
        [*test_command, *targets], cwd=work_dir, capture_output=True, text=True, check=False
    )
    outcome = verdict(done.returncode, done.stdout + done.stderr)

    if edit is not None:
        _git(repo_root, "checkout", "--", ".")
        _git(repo_root, "clean", "-fdq")
        if (after := _status(repo_root)) != before:
            return Result(
                ERROR,
                "the restore did not restore. STOP and repair the tree by hand; "
                f"every later verdict in this batch would be fiction. Now: {after[:120]!r}",
            )
    return outcome


def main(argv: list[str] | None = None) -> int:
    """Run one mutation from the command line."""
    parser = argparse.ArgumentParser(description=__doc__ and __doc__.splitlines()[0])
    parser.add_argument("label", help="what this mutation breaks, in a few words")
    parser.add_argument("-e", "--edit", help="shell command that applies it; omit for a baseline")
    parser.add_argument("target", nargs="+", help="pytest target path(s)")
    args = parser.parse_args(argv)

    repo_root = Path(
        subprocess.run(
            ["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, check=True
        ).stdout.strip()
    )
    result = run_mutation(
        args.edit,
        list(args.target),
        repo_root=repo_root,
        work_dir=Path(__file__).resolve().parents[2],
        test_command=list(DEFAULT_TEST_COMMAND),
    )
    print(result.line(args.label))
    return {CAUGHT: 0, SURVIVED: 1}.get(result.outcome, 2)


if __name__ == "__main__":
    sys.exit(main())
