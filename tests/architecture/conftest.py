"""Shared roots and helpers for architecture fitness-function tests.

These run alongside the rest of the suite but enforce structural invariants
the import graph, the AST, and the filesystem can prove. Tach (`tach.toml` at
the apps/keeper root) handles dependency-graph rules; everything under this
directory handles the rules tach cannot express: slice file contracts, decider
purity, completeness of wiring.

`SRC_ROOT` is computed relative to this file so the tests work whether pytest
runs from `apps/keeper/` (the Makefile target) or from the repository root (CI).

## Enumeration is git-aware, not filesystem-aware

`tracked_python_files()` returns the `.py` files under `src/keeper` that git is
TRACKING. Any fitness test that enumerates files MUST filter through this set
rather than scan the filesystem.

The reason is pre-commit: it stashes unstaged changes to tracked files but
never to untracked ones (pre-commit#1212 and #708, where the maintainer
rejected untracked-stash twice because it would clobber local venv and tox
state). Untracked files stay live on disk during a hook run. A filesystem scan
therefore sees a half-staged slice: an untracked handler beside stashed
wiring edits, and false-fails the wire-completeness checks.

Filtering through git's tracked set mirrors what pre-commit actually
evaluates: a slice in flight stays invisible until it is `git add`ed, at which
point every invariant applies to it at once.

The corollary is the trap. A file git has never seen is invisible to every one
of these checks, so a large green count says nothing about it. Stage new files
BEFORE trusting an architecture run.

## The empty-tree caveat

Most checks here iterate over discovered bounded contexts, and there are none.
They therefore pass by finding nothing to check, which is a false negative
rather than a green light. `test_fitness_scope.py` exists to make that state
visible and to fail the moment it changes.
"""

import os
import re
import subprocess
from functools import cache
from pathlib import Path

from tests._roots import APP_ROOT as _APP_ROOT
from tests._roots import REPO_ROOT

__all__ = ["REPO_ROOT"]
"""Re-exported, because most of this directory imports its roots from here.

`tests/_roots.py` is where both are derived, and the derivation is the
point: this used to count directory levels, which is an arithmetic fact
about a layout that is about to change.
"""

_MIGRATIONS_DIR = REPO_ROOT / "infra" / "atlas" / "migrations"

SRC_ROOT = _APP_ROOT / "src"
KEEPER_ROOT = SRC_ROOT / "keeper"
TESTS_ROOT = _APP_ROOT / "tests"

# Package names under `src/keeper` that are chassis, not bounded contexts.
# `discovered_bcs()` subtracts these; everything else is a BC.
NON_BC_PACKAGES: frozenset[str] = frozenset({"api", "infrastructure", "shared"})


@cache
def discovered_bcs() -> tuple[str, ...]:
    """Bounded-context package names under `src/keeper`, sorted.

    Derived from the tree rather than hand-listed, so a new BC is picked up by
    every fitness test at once instead of at the pace someone remembers to
    extend a tuple. `test_fitness_scope.py` pins the COUNT, which is what
    turns "derived" from a convenience into a check.
    """
    if not KEEPER_ROOT.is_dir():
        return ()
    return tuple(
        sorted(
            entry.name
            for entry in KEEPER_ROOT.iterdir()
            if entry.is_dir()
            and not entry.name.startswith("_")
            and entry.name not in NON_BC_PACKAGES
            and (entry / "__init__.py").exists()
        )
    )


@cache
def discovered_aggregates() -> tuple[str, ...]:
    """Aggregate folders across every bounded context, as `<bc>/<aggregate>`.

    Enumerated from git's tracked set, unlike `discovered_bcs()` which reads
    the directory tree. The asymmetry is deliberate: this mirrors what the
    rules in this directory actually range over, so the two counts disagreeing
    is itself the signal that a package exists on disk but its files are not
    staged, which is the shape of a green run that checked nothing.
    """
    bcs = set(discovered_bcs())
    found: set[str] = set()
    for path in tracked_python_files():
        parts = path.relative_to(KEEPER_ROOT).parts
        if len(parts) >= 4 and parts[0] in bcs and parts[1] == "aggregates":
            found.add(f"{parts[0]}/{parts[2]}")
    return tuple(sorted(found))


@cache
def discovered_tiers() -> tuple[str, ...]:
    """Test tier directories under `tests/`, as bare directory names.

    Read from the tree rather than from git, because a tier holding no
    tests yet is a real tier with no tracked `.py` file to find it by,
    and that is exactly the state in which a CI lane pointed at it fails
    on a fresh clone.

    A directory whose name starts with an underscore is shared machinery
    rather than a tier, the same convention the `features/` folders use
    for their private packages. `__pycache__` falls out of the same rule.
    """
    return tuple(
        sorted(
            path.name
            for path in TESTS_ROOT.iterdir()
            if path.is_dir() and not path.name.startswith((".", "_"))
        )
    )


@cache
def discovered_slices() -> tuple[str, ...]:
    """Slice folders across every bounded context, as `<bc>/<slice>`.

    Private folders (a leading underscore) are shared machinery inside a
    features/ directory rather than slices, and are excluded here for the same
    reason the slice rules exclude them.
    """
    bcs = set(discovered_bcs())
    found: set[str] = set()
    for path in tracked_python_files():
        parts = path.relative_to(KEEPER_ROOT).parts
        if (
            len(parts) >= 4
            and parts[0] in bcs
            and parts[1] == "features"
            and not parts[2].startswith("_")
        ):
            found.add(f"{parts[0]}/{parts[2]}")
    return tuple(sorted(found))


@cache
def tracked_python_files() -> frozenset[Path]:
    """Absolute paths to git-tracked `.py` files under `src/keeper`.

    See the module docstring for why fitness functions must enumerate from
    this set rather than from a filesystem scan. Cached because collection
    invokes the enumerators repeatedly.
    """
    return _tracked_python_files_under("src/keeper")


@cache
def tracked_test_files() -> frozenset[Path]:
    """Absolute paths to git-tracked `.py` files under `tests/`.

    Sibling of `tracked_python_files()`, same rationale: a fitness function
    that enumerates test-side files (helper naming, kernel construction sites)
    must filter through git's tracked set too.
    """
    return _tracked_python_files_under("tests")


def _tracked_python_files_under(subdir: str) -> frozenset[Path]:
    # Strip pre-commit's GIT_DIR and GIT_INDEX_FILE: inside a worktree they
    # point at the parent repo's hook staging area, which masks the worktree's
    # actual tracked files and silently checks the wrong set.
    env = {k: v for k, v in os.environ.items() if k not in {"GIT_DIR", "GIT_INDEX_FILE"}}
    result = subprocess.run(
        ["git", "ls-files", subdir],
        cwd=_APP_ROOT,
        capture_output=True,
        text=True,
        check=True,
        env=env,
    )
    return frozenset(
        _APP_ROOT / line for line in result.stdout.splitlines() if line.endswith(".py")
    )


@cache
def tracked_markdown_files() -> frozenset[Path]:
    """Absolute paths to git-tracked `.md` files under `docs/`.

    Rooted at the repo root rather than `apps/keeper`, because docs/ sits outside
    the API package. Keeps the same GIT_DIR strip for the same reason.
    """
    env = {k: v for k, v in os.environ.items() if k not in {"GIT_DIR", "GIT_INDEX_FILE"}}
    result = subprocess.run(
        ["git", "ls-files", "docs"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
        env=env,
    )
    return frozenset(
        REPO_ROOT / line for line in result.stdout.splitlines() if line.endswith(".md")
    )


@cache
def tracked_file_basenames() -> frozenset[str]:
    """Every git-tracked file in the repository, by basename alone.

    For the one check that asks whether a path a docstring cites still
    exists. Basenames rather than paths because a citation is prose and
    may be written from any directory's point of view; the question it
    answers is whether the reader has something to open.

    Enumerated from git rather than from a filesystem walk, and that is
    the whole reason this exists. An `rglob` from the repo root descends
    into `.claude/worktrees/`, where another session's checkout holds its
    own copy of the tree, so a citation of a file deleted here resolves
    against a stale copy over there and the check passes. That is the
    same hazard the GIT_DIR strip below guards, reached by a different
    route.
    """
    env = {k: v for k, v in os.environ.items() if k not in {"GIT_DIR", "GIT_INDEX_FILE"}}
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
        env=env,
    )
    return frozenset(line.rsplit("/", 1)[-1] for line in result.stdout.splitlines() if line)


@cache
def tracked_migration_files() -> tuple[Path, ...]:
    """Git-tracked `.sql` files under `infra/atlas/migrations/`, sorted.

    Migration-aware sibling of the two above, for the same pre-commit reason:
    a half-staged migration on disk would otherwise leak into an architecture
    run and false-fail the GRANT and REVOKE checks.

    Returns a tuple, not a frozenset, because migration ORDER is semantically
    meaningful: a later `ALTER ... RENAME` or `DROP` discards an earlier
    `CREATE`, and a walker that folds them in the wrong order gets the current
    schema wrong.
    """
    env = {k: v for k, v in os.environ.items() if k not in {"GIT_DIR", "GIT_INDEX_FILE"}}
    result = subprocess.run(
        ["git", "ls-files", "infra/atlas/migrations"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
        env=env,
    )
    return tuple(
        sorted(REPO_ROOT / line for line in result.stdout.splitlines() if line.endswith(".sql"))
    )


_CREATE_TABLE_RE = re.compile(
    r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([a-zA-Z_][a-zA-Z0-9_]*)",
    re.IGNORECASE,
)
_RENAME_TABLE_RE = re.compile(
    r"ALTER\s+TABLE\s+([a-zA-Z_][a-zA-Z0-9_]*)\s+RENAME\s+TO\s+([a-zA-Z_][a-zA-Z0-9_]*)",
    re.IGNORECASE,
)


def append_only_table_lineage() -> dict[str, frozenset[str]]:
    """Every currently append-only table, keyed by its current name.

    Maps each to every name it has ever held, because a GRANT or REVOKE may
    have been issued under an older name and a caller searching for that fact
    needs the whole chain.

    Renames are followed across ALL tables, not only those already matching
    the append-only prefix. A table can ENTER the family through a rename
    whose old name never matched, and gating the follow on "the old name
    already looked append-only" would silently drop that chain.
    """
    lineage: dict[str, set[str]] = {}
    for path in tracked_migration_files():
        text = path.read_text()
        for match in _CREATE_TABLE_RE.finditer(text):
            name = match.group(1)
            lineage.setdefault(name, {name})
        for match in _RENAME_TABLE_RE.finditer(text):
            old_name, new_name = match.group(1), match.group(2)
            if old_name in lineage:
                names = lineage.pop(old_name)
                names.add(new_name)
                lineage[new_name] = names
    return {
        name: frozenset(names)
        for name, names in lineage.items()
        if name == "events" or name.startswith("entries_")
    }
