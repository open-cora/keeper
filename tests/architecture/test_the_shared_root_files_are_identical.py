"""Files every project carries a copy of must be the same copy.

Four files are duplicated rather than shared, because three projects that
build and ship separately cannot import one another and a repository has
to hold its own licence, its own Python pin and its own scanning workflow.
Duplication is the right answer and drift is what makes it the wrong one.

## Why this check cannot outlive the split

It reaches across `apps/` to compare three trees, which is possible for
exactly as long as those trees share a checkout. Once each project is a
repository of its own there is nothing here to compare, and this file
should be deleted rather than adapted: a copy of it in one repository
could only check that repository against itself.

That is the whole reason it is worth having now. This is the window in
which a copy can be edited on one side and not the others, and after it
closes the copies drift by a slower mechanism that a test cannot see.

## What is deliberately not here

`CLAUDE.md`, `CONTRIBUTING.md`, `SECURITY.md`, `CITATION.cff`, the
`Makefile`, the pre-commit config and the CI workflow. Every one of those
exists in all three projects and every one says something different in
each, because each describes its own tree. Comparing them would be
comparing three answers to three questions.
"""

from pathlib import Path

import pytest

from tests._roots import REPO_ROOT

pytestmark = pytest.mark.architecture

SHARED_FILES: tuple[str, ...] = (
    "LICENSE",
    ".python-version",
    ".gitignore",
    ".github/workflows/codeql.yml",
)
"""Paths each project carries a byte-identical copy of.

An entry earns its place by saying nothing about the project it sits in.
The licence is the same grant, the Python pin is the same interpreter, the
ignore rules name the same tooling, and the scanning workflow runs the
same analysis. A file that would need one word changed per project does
not belong here; it belongs in the list the module docstring refuses.
"""

PROJECTS: tuple[tuple[str, str], ...] = (
    ("keeper", "."),
    ("conductor", "apps/conductor"),
    ("reporter", "apps/reporter"),
)
"""Each project, and the directory that becomes its repository root.

The keeper's is the checkout itself, because the keeper is what this
repository becomes: the root files are already its files and a second copy
under `apps/keeper` would be the drift this module exists to catch.

Written out per project rather than probed for. An earlier version looked
for a project's own copy and fell back to the root when it found none,
which made the keeper's case work and made a client that had LOST its copy
indistinguishable from one that never needed it. Deleting the reporter's
licence passed.
"""


def _copy_path(base: str, relative: str) -> Path:
    """Where the project rooted at `base` keeps its copy of `relative`."""
    return REPO_ROOT / base / relative


def test_every_project_directory_exists() -> None:
    """Guard the enumeration: a renamed project silently drops out.

    Without this, a typo in `PROJECTS` would compare two copies instead of
    three and report green on the pair that happened to agree.
    """
    missing = [base for _, base in PROJECTS if not (REPO_ROOT / base).is_dir()]
    assert not missing, f"Listed projects that are not directories: {missing}"


@pytest.mark.parametrize("relative", SHARED_FILES)
def test_a_shared_file_is_present_in_every_project(relative: str) -> None:
    """A project missing its copy would ship without the file entirely.

    Checked before the contents are compared, because a missing file and a
    changed one need different fixes and `read_text` would raise for the
    first while naming neither.
    """
    absent = [name for name, base in PROJECTS if not _copy_path(base, relative).is_file()]
    assert not absent, (
        f"{relative} is missing from {absent}. Each project becomes a "
        "repository of its own, and a repository without this file ships "
        "without it."
    )


@pytest.mark.parametrize("relative", SHARED_FILES)
def test_every_copy_of_a_shared_file_is_byte_identical(relative: str) -> None:
    contents = {name: _copy_path(base, relative).read_bytes() for name, base in PROJECTS}
    distinct = set(contents.values())
    assert len(distinct) == 1, (
        f"{relative} differs between projects: "
        f"{ {p: len(v) for p, v in contents.items()} }.\n"
        "These are duplicated rather than shared, so nothing but this check "
        "keeps them in step. Either copy the intended version across, or, if "
        "this file now has to say something different per project, drop it "
        "from SHARED_FILES and say why in the module docstring."
    )


def test_the_keeper_keeps_its_copies_at_the_repository_root() -> None:
    """The fallback in `_copy_path` is load-bearing, so pin what it means.

    If the keeper ever grew its own `apps/keeper/LICENSE`, this rule would
    start comparing that one and the root file would go unchecked while
    still being the one a reader finds. Both would then be shipped by the
    split, one of them stale.
    """
    shadowed = [f for f in SHARED_FILES if (REPO_ROOT / "apps" / "keeper" / f).exists()]
    assert not shadowed, (
        f"apps/keeper carries its own {shadowed}, shadowing the root copy "
        "this rule compares against. The keeper's copies are the root files."
    )
