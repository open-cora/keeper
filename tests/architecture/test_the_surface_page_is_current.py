"""The generated surface page matches the code it was generated from.

`docs/surface.md` lists every route and every MCP tool in one place. It is
written by `scripts/generate_surface.py` and committed, so a mirror needs
no build step to have it and a reviewer sees a new route arrive in a diff.

Committed generated files go stale the moment somebody forgets the command,
and nothing about writing "do not edit" at the top of one prevents that.
This is what prevents it. A slice added without regenerating fails here,
and so does a hand edit.

## Why this runs the script instead of importing it

The script is not importable from the suite without putting `scripts/` on
`sys.path` first, and a path insert at the top of a test file is machinery
hiding a structural problem: the runtime import resolves and the type
checker cannot see it, so the whole file quietly degrades to unknown types.
That happened, and it cost a green pytest run beside a red typecheck.

Running it as a subprocess removes the question. It also checks the thing a
person actually does, which is run the command, rather than a function the
command happens to call.
"""

import subprocess
import sys

import pytest

from tests._roots import APP_ROOT

pytestmark = pytest.mark.architecture

_SCRIPT = APP_ROOT / "scripts" / "generate_surface.py"
_PAGE = APP_ROOT / "docs" / "surface.md"


def test_the_committed_surface_page_lists_the_operations_it_claims_to() -> None:
    """Guard the derivation: an empty page would match an empty render.

    The check below compares two things that are equal when both are blank,
    which is the state a broken parse produces, so something has to assert
    that the page has operations on it at all.
    """
    assert _PAGE.exists(), f"{_PAGE} is missing. Run: make docs-surface"
    rows = [
        line for line in _PAGE.read_text(encoding="utf-8").splitlines() if line.startswith("| `")
    ]
    assert len(rows) > 40, f"The surface page lists only {len(rows)} operations, which is too few."


def test_regenerating_the_surface_page_changes_nothing() -> None:
    result = subprocess.run(
        [sys.executable, str(_SCRIPT), "--check"],
        capture_output=True,
        text=True,
        cwd=APP_ROOT,
        check=False,
    )
    assert result.returncode == 0, (
        "docs/surface.md does not match the code it is generated from.\n\n"
        "Run: make docs-surface\n\n"
        "This happens when a slice is added, a route or a tool is renamed, or "
        "somebody edited the page by hand. The page is generated: edit the "
        "generator or the code, never the page.\n\n"
        f"{result.stdout}{result.stderr}"
    )
