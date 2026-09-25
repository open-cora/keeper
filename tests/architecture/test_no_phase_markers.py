"""No phase, iteration, or audit tags in source, tests or documentation.

`Phase 8f-d`, `Iter B-3`, `slice 5g-c`, `audit-2026-05-20`: these name a moment
in a plan, and they rot the moment the plan moves. The current code is what is
true; ordering lives in git history.

The check is literal AND shape-based, because the literal forms are easy to
avoid by accident while the shape (`6g-c`, `5g-a`) reads as a coordinate and
sneaks through review.

## Why all three, and not just `src`

This reached `src/keeper` alone, which left the larger half of the prose
unchecked: `docs/` is where a plan coordinate is most tempting to write,
because a page explaining why something is the way it is has the history
fresh in mind. The client packages next door check their source, their tests
and their pages together, and there is no reason this tree should be the
lenient one.

Widening it cost two rewrites and one exclusion, which is the usual price and
the reason the rule is cheap.
"""

import re
from pathlib import Path

import pytest

from tests.architecture.conftest import (
    tracked_prose_files,
    tracked_python_files,
    tracked_test_files,
)

pytestmark = pytest.mark.architecture

_PATTERNS = (
    # Separator-agnostic: `Phase 8e`, `Phase-8e` and `Phase_8e` are one tag
    # wearing three coats, and the whitespace-only form let three through.
    re.compile(r"\bPhase[\s_-]*\d", re.IGNORECASE),
    re.compile(r"\bIter(ation)?[\s_-]*[A-Z]-?\d", re.IGNORECASE),
    re.compile(r"\bslice\s+\d+[a-z]\b", re.IGNORECASE),
    re.compile(r"\baudit-20\d\d-\d\d-\d\d\b", re.IGNORECASE),
    # A bare plan coordinate such as 6g-c or 5g-a: digit, letter, dash, letter.
    re.compile(r"\b\d+[a-z]-[a-z]\b"),
    # A review-finding reference: `gate-review F2`, `SEC S2`, `impl#11`,
    # `test#6`, `BLOCKING F1`. Same rot as a phase tag and one step worse:
    # it points at a numbered finding in a review whose document does not
    # travel with the code, so a reader cannot look it up even in principle.
    # 25 of these came across with the chassis.
    re.compile(r"\bgate.review\b", re.IGNORECASE),
    re.compile(r"\b(impl|test|review)#\d+", re.IGNORECASE),
    # The finding codes themselves. The comment above listed `SEC S2` and
    # `BLOCKING F1` as examples of what this test catches, and neither
    # pattern above matches either of them, so a `GR3 RISK-1 + RISK-4`
    # tag sat in a docstring through the whole infrastructure sweep. The
    # prefixes are enumerated rather than generalized because the obvious
    # generalization (uppercase word, then a number) also swallows
    # `RFC 9728`, `PEP 258`, `HTTP 401` and `ISA-95`.
    re.compile(r"\b(GR|SEC|BLOCKING|RISK|FINDING)[\s_-]?[A-Z]?-?\d+\b"),
)


_THIS_FILE = "test_no_phase_markers.py"
"""The one file excluded, because it has to name what it refuses.

Scanning it fails on its own patterns and on its own worked examples. The
cost is that a real tag written into this file goes unseen, which is the
narrowest hole available: any file defining these forms has to spell them.
"""


def _offenders(paths: frozenset[Path]) -> list[str]:
    hits: list[str] = []
    for path in sorted(paths):
        if path.name == _THIS_FILE:
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if any(pattern.search(line) for pattern in _PATTERNS):
                hits.append(f"{path}:{lineno}: {line.strip()}")
    return hits


def test_the_tag_scan_reaches_source_tests_and_documentation() -> None:
    """Guard the enumeration: an empty file set makes the rule vacuous."""
    assert tracked_python_files(), "No source file scanned."
    assert tracked_test_files(), "No test file scanned."
    assert tracked_prose_files(), "No prose scanned."


def test_tracked_files_carry_no_phase_markers() -> None:
    hits = _offenders(tracked_python_files() | tracked_test_files() | tracked_prose_files())
    assert not hits, (
        "Phase / iteration / audit tag in source, tests or documentation. "
        "Git log is the right home:\n" + "\n".join(hits)
    )
