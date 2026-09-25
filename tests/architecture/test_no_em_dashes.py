"""No em dashes or en dashes in source or docs.

Per the writing-style rule in CLAUDE.md: substitute a comma, a colon, a
semicolon, or rephrase.

There is no allowlist, and that is the point. The tree this repository was
seeded from carries a 562-file ratchet because the rule arrived after the
prose did; here the prose was scrubbed before the first commit, so the rule
can simply hold. Keep it that way: an allowlist added now would start the
same ratchet over.
"""

from pathlib import Path

import pytest

from tests.architecture.conftest import tracked_markdown_files, tracked_python_files

pytestmark = pytest.mark.architecture

_EM_DASH = "\u2014"
_EN_DASH = "\u2013"


def _offenders(paths: frozenset[Path]) -> list[str]:
    hits: list[str] = []
    for path in sorted(paths):
        for lineno, line in enumerate(path.read_text().splitlines(), 1):
            if _EM_DASH in line or _EN_DASH in line:
                hits.append(f"{path}:{lineno}: {line.strip()}")
    return hits


def test_tracked_python_files_carry_no_em_dashes() -> None:
    hits = _offenders(tracked_python_files())
    assert not hits, "Em or en dash in source:\n" + "\n".join(hits)


def test_tracked_markdown_files_carry_no_em_dashes() -> None:
    hits = _offenders(tracked_markdown_files())
    assert not hits, "Em or en dash in docs:\n" + "\n".join(hits)
