"""Every test tier is run by a lane, and every lane names a path that exists.

Two failure modes, opposite to each other, and both silent.

Forward: a tier directory no lane names never runs. pytest is perfectly
happy to collect a subset and report green, so the tests are still there,
still passing locally, and no longer defended by anything.

Reverse: a lane naming a path that is not there. Git does not track an
empty directory, so a tier holding no tests yet is absent from a fresh
clone even though it is present on the author's machine, and the lane
fails with "file or directory not found" before running a single test.

This check used to be a shell step inside the CI workflow. It moved here
for the reason its own subject describes: nobody could run it. A private
helper package landed under `tests/` in the commit before this one, the
step's hand-written allowlist did not know about it, and the CI lint job
would have failed on a tree that was green in every local gate. The
allowlist also still carried a `fixtures` entry for a directory that does
not exist. Both problems are what a rule written where it cannot be run
turns into.

The allowlist is gone rather than corrected. A directory under `tests/`
is a tier unless its name starts with an underscore, which is the same
private-package convention the `features/` folders already use, so shared
machinery declares itself in its own name and needs no list.

Both lane files are read, and both must name every tier. The Makefile is
the local mirror of the workflow, and a mirror nobody compares is how the
two drift until a change passes `make test-noio` and fails in CI.
"""

import re
from functools import cache
from pathlib import Path

import pytest

from tests.architecture.conftest import REPO_ROOT, TESTS_ROOT, discovered_tiers

pytestmark = pytest.mark.architecture

_LANE_FILES: tuple[Path, ...] = (
    REPO_ROOT / "Makefile",
    REPO_ROOT / ".github" / "workflows" / "ci.yml",
)

_TIER_PATH = re.compile(r"(?<![\w/])tests/([a-z0-9_]+)")
"""A `tests/<tier>` path on a command line.

The lookbehind keeps `scripts/tests/...` and similar out, so another
project's directory cannot be mistaken for a lane of this one.
"""


@cache
def _tiers_named_by(lane_file: Path) -> frozenset[str]:
    """Tier directories named on a pytest command line in one file.

    Only lines mentioning pytest count. A tier named in a comment or in
    prose is not being run by anything, and reading those too would let
    a sentence about a tier stand in for a lane that executes it.
    """
    named: set[str] = set()
    for line in lane_file.read_text(encoding="utf-8").splitlines():
        if "pytest" in line:
            named.update(_TIER_PATH.findall(line))
    return frozenset(named)


def _lane_id(path: Path) -> str:
    return path.name


def test_the_lane_scan_finds_tiers_in_every_lane_file() -> None:
    """Guard the derivation: a parse that finds nothing passes everything.

    The reverse rule below iterates over what each file names, so a
    regex that stopped matching would leave it iterating over nothing
    and reporting green on a question it had stopped asking.
    """
    assert discovered_tiers(), "No tier directory found under tests/."
    for lane_file in _LANE_FILES:
        # Checked before it is read, because both of these sit outside this
        # project and are reached through the repository root. A root that
        # moved raises FileNotFoundError from inside a cached helper, which
        # names neither the cause nor the cure.
        assert lane_file.is_file(), (
            f"{lane_file} is not there, so this rule can read no lane at all. "
            "Both lane files are resolved against the repository root; if "
            "this project moved, that is the thing to check first."
        )
        assert _tiers_named_by(lane_file), (
            f"No tests/<tier> path found on any pytest line in {lane_file.name}, "
            "so the lane derivation has stopped working."
        )


@pytest.mark.parametrize("tier", discovered_tiers())
def test_a_tier_directory_is_run_by_both_lane_files(tier: str) -> None:
    missing = [f.name for f in _LANE_FILES if tier not in _tiers_named_by(f)]
    assert not missing, (
        f"tests/{tier} is not run by {missing}.\n"
        "A tier no lane names still passes locally and is defended by "
        "nothing. Add it to the lane that matches what it needs to run: "
        "test-noio for tiers that reach no database, test-db for the rest.\n"
        "If it is shared machinery rather than a tier, rename the directory "
        "with a leading underscore and it stops counting as one."
    )


@pytest.mark.parametrize("lane_file", _LANE_FILES, ids=_lane_id)
def test_every_path_a_lane_names_is_a_directory_that_exists(lane_file: Path) -> None:
    absent = sorted(t for t in _tiers_named_by(lane_file) if not (TESTS_ROOT / t).is_dir())
    assert not absent, (
        f"{lane_file.name} names tests/{absent} which is not there.\n"
        "Git does not track an empty directory, so a tier with no tests yet "
        "vanishes on a fresh clone and the lane fails before running "
        "anything. Add a tracked placeholder (see tests/e2e/README.md) or "
        "drop the path from the lane."
    )
