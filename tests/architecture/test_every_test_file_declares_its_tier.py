"""Every test file says which tier it is in, and says the same as its folder.

The tier decides which CI lane runs a test, and it is written down twice:
once as the directory a file sits in, and once as the `pytestmark` inside
it. Both selectors currently pick the same 469 tests, so the duplication
is invisible, which is the problem. A file that forgets its marker still
runs today, because the lanes select by path, and nothing anywhere
notices the omission.

Every test file carries a marker right now, all of them, by habit. Habit
is what stops holding when a repository grows, and a marker cannot be
restored later by reading the file: somebody has to decide what the test
needs to run. So the habit becomes a rule while it is still free, which
also means the two selectors can be trusted to agree and the folder
layout can change without touching CI.

Agreement is worth checking rather than assuming, because the two sides
are written by different acts. A marker is typed into the file; the
folder is where the author dropped it. A file marked `unit` sitting in
`integration` would run in the no-database lane if selection ever moved
to markers, and fail there with no database to reach.

The tier is the FIRST path segment under `tests/`, not the immediate
parent, so a later `tests/unit/access/` groups by bounded context without
changing anything here.
"""

import ast
from functools import cache
from pathlib import Path

import pytest

from tests.architecture.conftest import TESTS_ROOT, discovered_tiers, tracked_test_files

pytestmark = pytest.mark.architecture


def _marker_names(node: ast.expr) -> frozenset[str]:
    """Marker names in one `pytestmark` value, whatever shape it takes.

    Recursive because the forms nest: a list of markers, and a marker
    that is a call such as `pytest.mark.skipif(...)`. Anything that is
    not a `pytest.mark.<name>` reference contributes nothing rather than
    raising, so an unusual but legal value fails the rule below with a
    readable message instead of an error here.
    """
    if isinstance(node, ast.Call):
        return _marker_names(node.func)
    if isinstance(node, ast.List | ast.Tuple):
        names: set[str] = set()
        for element in node.elts:
            names |= _marker_names(element)
        return frozenset(names)
    if isinstance(node, ast.Attribute):
        parent = node.value
        if isinstance(parent, ast.Attribute) and parent.attr == "mark":
            return frozenset({node.attr})
    return frozenset()


def _declared_markers(source: str) -> frozenset[str]:
    """Markers a module declares at module level via `pytestmark`.

    Module level only. A `pytestmark` inside a class applies to that
    class and cannot be what a lane selects the file by.
    """
    markers: set[str] = set()
    for node in ast.parse(source).body:
        if not isinstance(node, ast.Assign):
            continue
        if any(isinstance(t, ast.Name) and t.id == "pytestmark" for t in node.targets):
            markers |= _marker_names(node.value)
    return frozenset(markers)


@cache
def _test_files() -> tuple[Path, ...]:
    """Every tracked file pytest will collect as tests."""
    return tuple(sorted(p for p in tracked_test_files() if p.name.startswith("test_")))


def _file_id(path: Path) -> str:
    return str(path.relative_to(TESTS_ROOT))


def test_the_tier_scan_finds_at_least_one_test_file_and_one_tier() -> None:
    """Guard both sides: either one empty makes the rules below vacuous."""
    assert _test_files(), "No tracked test file found, so the marker rule ran against nothing."
    assert discovered_tiers(), "No tier directory found under tests/."


_MARKER_FORMS: tuple[tuple[str, str, frozenset[str]], ...] = (
    ("single", "pytestmark = pytest.mark.unit", frozenset({"unit"})),
    ("in a list", "pytestmark = [pytest.mark.integration]", frozenset({"integration"})),
    ("in a tuple", "pytestmark = (pytest.mark.contract,)", frozenset({"contract"})),
    (
        "several",
        "pytestmark = [pytest.mark.unit, pytest.mark.slow]",
        frozenset({"unit", "slow"}),
    ),
    ("a call", 'pytestmark = pytest.mark.skipif(True, reason="x")', frozenset({"skipif"})),
    ("absent", "x = 1", frozenset()),
    ("inside a class", "class T:\n    pytestmark = pytest.mark.unit\n", frozenset()),
)


@pytest.mark.parametrize(
    ("source", "expected"),
    [(source, expected) for _label, source, expected in _MARKER_FORMS],
    ids=[label for label, _source, _expected in _MARKER_FORMS],
)
def test_the_marker_scan_reads_every_form_a_pytestmark_can_take(
    source: str, expected: frozenset[str]
) -> None:
    """Run the scan over inputs of this table's choosing, not the tree's.

    Four of these forms appear in the tree today and three do not. A scan
    blind to a form nobody has used yet would pass here forever and go
    quiet the first time somebody used it, reporting a missing marker on
    a file that has one.
    """
    assert _declared_markers(source) == expected


@pytest.mark.parametrize("path", _test_files(), ids=_file_id)
def test_a_test_file_declares_the_tier_of_the_folder_it_sits_in(path: Path) -> None:
    relative = path.relative_to(TESTS_ROOT)
    assert len(relative.parts) > 1, (
        f"{relative} sits directly in tests/ rather than inside a tier.\n"
        "Every CI lane names tier directories, so a file at the top level "
        "is collected by no lane and runs nowhere."
    )

    tier = relative.parts[0]
    declared = _declared_markers(path.read_text(encoding="utf-8"))
    assert declared, (
        f"{relative} declares no module-level pytestmark.\n"
        f"Add `pytestmark = pytest.mark.{tier}`. The lanes select by path "
        "today, so this file does run, and that is why nothing else notices."
    )
    assert tier in declared, (
        f"{relative} is in the {tier} tier but declares {sorted(declared)}.\n"
        "The folder and the marker are two statements of the same fact, "
        "written by different hands. Selection by path follows the folder "
        "and selection by marker follows the marker, so while they disagree "
        "the file runs in one lane and not the other."
    )
