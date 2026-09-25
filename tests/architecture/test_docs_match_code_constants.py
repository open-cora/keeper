"""A list written out in a docs page must match the constant it claims to name.

A prose list and a frozenset are two independent sides of the same fact, which
is the condition under which a check is worth writing: the docs page cannot
drift from the code without one of them being wrong, and nothing else notices
which. `conventions.md` listed four unit systems while the allowlist enforced
five, so a reader following the page would have believed a valid namespace was
rejected.

Three entries. The mechanism generalizes to any docs claim that names a
closed set or a counted one in code; the cost of an entry is one row below.

The second entry was added after the page and the code disagreed for a
second time, and worse than the first. `conventions.md` told an author to
close every schema with `additionalProperties: false`, which the subset
forbids outright, so the page's advice produced a 400. It also described
the keyword rule as a denylist of four when the code is an allowlist of
nine. Nothing tied the two together, which is the only reason either could
happen.

The third is the documentation home page, which prints the three fitness
scope counts and then says they are pinned so they cannot drift. They were
not: the page read 15 slices while the code had 17, and the sentence
claiming otherwise is the reason nobody looked. A page asserting its own
enforcement is the one kind of staleness a reader cannot detect by
reading, which makes it the kind most worth a check.
"""

import re

import pytest

from keeper.shared.json_schema.subset import ALLOWED_SCHEMA_KEYS
from keeper.shared.json_schema.validation import ALLOWED_UNIT_SYSTEMS
from tests.architecture.conftest import REPO_ROOT
from tests.architecture.test_fitness_scope import (
    EXPECTED_AGGREGATE_COUNT,
    EXPECTED_BC_COUNT,
    EXPECTED_SLICE_COUNT,
)

pytestmark = pytest.mark.architecture

_CONVENTIONS = REPO_ROOT / "docs" / "reference" / "conventions.md"
_HOME = REPO_ROOT / "docs" / "index.md"

_SCOPE_COUNT_LINES: tuple[tuple[str, str, int], ...] = (
    ("bounded contexts", r"^   bounded contexts\s+(\d+)\s", EXPECTED_BC_COUNT),
    ("aggregates", r"^   aggregates\s+(\d+)\s", EXPECTED_AGGREGATE_COUNT),
    ("slices", r"^   slices\s+(\d+)\s", EXPECTED_SLICE_COUNT),
)
"""The three counts the home page prints, and the pins they must equal.

Imported from the fitness-scope module rather than recomputed, so this
compares the page against the same integer a reader would find by
following the sentence next to the block.
"""

_SCHEMA_KEYWORD_LINE = re.compile(r"^- \*\*Allowed anywhere in a schema\*\*: \(([^)]*)\)\.")
"""The bullet in the schema section that spells the allowlist out in prose.

Anchored on the whole bullet like its neighbour below, so a rewrite that
moves the list fails loudly here instead of matching nothing and passing.
"""

_UNIT_SYSTEM_LINE = re.compile(r"^- \*\*`system`\*\*: namespace identifier \(([^)]*)\)\.")
"""The bullet in the units section that spells the allowlist out in prose.

Anchored on the whole bullet rather than on the names, so a rewrite that moves
the list somewhere else fails loudly here instead of matching nothing and
passing.
"""


def test_the_conventions_page_is_readable_at_the_path_this_check_uses() -> None:
    """Guard the read, so a moved page cannot make the check below vacuous."""
    assert _CONVENTIONS.is_file(), f"No conventions page at {_CONVENTIONS}"


def test_docs_unit_systems_match_the_allowlist() -> None:
    text = _CONVENTIONS.read_text()
    matches = [_UNIT_SYSTEM_LINE.match(line) for line in text.splitlines()]
    found = [m for m in matches if m is not None]
    assert len(found) == 1, (
        "Expected exactly one `system` bullet in the units section of "
        f"conventions.md, found {len(found)}. If the bullet was reworded, "
        "update _UNIT_SYSTEM_LINE here in the same commit."
    )

    documented = set(re.findall(r"`([a-z0-9]+)`", found[0].group(1)))
    assert documented == set(ALLOWED_UNIT_SYSTEMS), (
        "The unit systems listed in docs/reference/conventions.md disagree with "
        "ALLOWED_UNIT_SYSTEMS. Documented but not allowed: "
        f"{sorted(documented - set(ALLOWED_UNIT_SYSTEMS))}. Allowed but not "
        f"documented: {sorted(set(ALLOWED_UNIT_SYSTEMS) - documented)}."
    )


def test_docs_schema_keywords_match_the_allowlist() -> None:
    """The stored subset, as the page states it and as the code enforces it.

    Backticked tokens are pulled out rather than split on commas, because
    `$schema` carries a sigil and a comma-split would also swallow the
    surrounding prose if the bullet were ever reworded mid-sentence.
    """
    text = _CONVENTIONS.read_text()
    matches = [_SCHEMA_KEYWORD_LINE.match(line) for line in text.splitlines()]
    found = [m for m in matches if m is not None]
    assert len(found) == 1, (
        "Expected exactly one allowed-keywords bullet in the schema section of "
        f"conventions.md, found {len(found)}. If the bullet was reworded, "
        "update _SCHEMA_KEYWORD_LINE here in the same commit."
    )

    documented = set(re.findall(r"`([$A-Za-z][A-Za-z0-9]*)`", found[0].group(1)))
    assert documented == set(ALLOWED_SCHEMA_KEYS), (
        "The schema keywords listed in docs/reference/conventions.md disagree "
        "with ALLOWED_SCHEMA_KEYS. Documented but not allowed: "
        f"{sorted(documented - set(ALLOWED_SCHEMA_KEYS))}. Allowed but not "
        f"documented: {sorted(set(ALLOWED_SCHEMA_KEYS) - documented)}.\n"
        "Widening the allowlist means widening the page in the same commit, "
        "and a keyword that takes a schema also means teaching check_subset "
        "to recurse into it."
    )


def test_the_home_page_is_readable_at_the_path_this_check_uses() -> None:
    """Guard the path, so a moved page fails loudly instead of vacuously."""
    assert _HOME.is_file(), f"{_HOME} is missing, so the count checks read nothing."


@pytest.mark.parametrize(
    ("label", "pattern", "expected"),
    _SCOPE_COUNT_LINES,
    ids=[label for label, _pattern, _expected in _SCOPE_COUNT_LINES],
)
def test_the_home_page_counts_match_the_fitness_scope_pins(
    label: str, pattern: str, expected: int
) -> None:
    """The home page prints these and claims they cannot drift.

    They could, and they had. The block is a code fence rather than a
    bullet, so the anchor is the row's label and leading spaces; a rewrite
    that reformats the block fails here rather than matching nothing.
    """
    found = re.findall(pattern, _HOME.read_text(encoding="utf-8"), re.MULTILINE)
    assert len(found) == 1, (
        f"Expected exactly one '{label}' row in the home page's count block, "
        f"found {len(found)}. If the block was reformatted, update the pattern "
        "here in the same commit."
    )
    assert int(found[0]) == expected, (
        f"docs/index.md says {found[0]} {label}; test_fitness_scope.py pins "
        f"{expected}. The page says these cannot drift, so make that true."
    )
