"""Where this project sits, and where the repository around it sits.

One derivation, imported by both conftests. There were three before: the
architecture conftest counted two directories up from itself and then two
more, the root conftest counted three up, and the mutation harness asked
git. The first one's own docstring warned that two spellings of a root is
how they end up disagreeing about which directory they are looking in,
which is what this module exists to stop.

## Why the repository root comes from git

Counting directory levels encodes the current layout as an arithmetic
fact, and the layout is about to change: this project moves to the root
of a repository of its own. A count that is right today is then two
levels too high, and what it names is the directory holding the
checkout. Nothing about that is loud. `git ls-files` run there succeeds
whenever the parent happens to be tracked too, so the enumerators come
back with another repository's files and every rule that ranges over
them passes, having examined the wrong tree.

Asking git removes the arithmetic. It is also what
`tests/_mutation/harness.py` already did, so this makes one answer out of
two rather than inventing a third.

## Why the project root is still counted

`APP_ROOT` is two directories above this file, which is correct both in
the tree today and in the flattened one: this module sits at
`tests/_roots.py` either way. The checks below are what say so out loud
rather than leaving it to be rediscovered.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1]
"""The directory holding this project's `pyproject.toml`.

Its source is `src/`, its suite is `tests/`, and it is what `git ls-files`
is run from when a rule ranges over this project alone.
"""


def _git_toplevel(start: Path) -> Path:
    """The root of the working tree holding `start`, as git reports it.

    GIT_DIR and GIT_INDEX_FILE are stripped for the reason the enumerators
    strip them: pre-commit points them at its own staging area, and inside
    a worktree they name the parent checkout rather than this one.
    """
    env = {k: v for k, v in os.environ.items() if k not in {"GIT_DIR", "GIT_INDEX_FILE"}}
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=start,
        capture_output=True,
        text=True,
        check=True,
        env=env,
    )
    return Path(result.stdout.strip()).resolve()


REPO_ROOT = _git_toplevel(APP_ROOT)
"""The root of the repository this project is checked out in.

The same directory as `APP_ROOT` once this project is a repository of its
own, and two above it until then. Rules reaching `infra/`, `docs/` or the
CI workflow resolve against this one.
"""

if not (REPO_ROOT / ".git").exists():
    raise RuntimeError(
        f"{REPO_ROOT} has no .git, so it is not a repository root. Every "
        "rule that enumerates tracked files resolves against it, and a "
        "wrong one makes them range over the wrong tree quietly."
    )

if not APP_ROOT.is_relative_to(REPO_ROOT):
    raise RuntimeError(
        f"{APP_ROOT} is not inside {REPO_ROOT}, so the two roots disagree about which tree this is."
    )
