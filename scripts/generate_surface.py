"""Write `docs/surface.md` from the slices on disk.

Every operation this system has exists twice, as an HTTP route and as an
MCP tool, and until this page existed the only way to see them all was to
read six context pages and union their tables. A caller deciding what to
call should not have to do that, and neither should anybody auditing what
this system exposes.

The page is generated rather than written, and committed rather than built
on the fly, for two reasons. A mirror builds its own site with nothing
beside it, so a page produced by a build step is a build step the mirror
has to carry. And a committed page shows up in a diff, which is how a
reviewer sees that a change added a route.

What keeps it honest is `tests/architecture/test_the_surface_page_is_current.py`,
which runs this and fails on any difference. So the page cannot drift from
the code even though nothing regenerates it automatically.

## Why this reads the source rather than the running app

The app is the better authority on what is served, and it cannot answer
the question this page asks. FastAPI knows its routes and the MCP server
knows its tools, and nothing in either knows that one route and one tool
are the same operation. What knows is the directory holding both, so that
is what this reads.

The live surface is pinned elsewhere, by the contract tier, which drives
the mounted MCP endpoint and compares what it publishes against a list.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1]
SRC = APP_ROOT / "src" / "keeper"
PAGE = APP_ROOT / "docs" / "surface.md"

NON_BC = frozenset({"api", "infrastructure", "shared"})

_ROUTE = re.compile(r'@router\.(get|post|put|patch|delete)\(\s*\n\s*"([^"]+)"(.*?)\n\)', re.S)
"""The one route a slice declares: its method, its path, and the rest of the call.

Anchored on the decorator opening a new line with a quoted path, which is
how every slice in this tree writes it. A slice that wrote it some other
way parses as having no route and fails the completeness check below
rather than being skipped.
"""

_STATUS = re.compile(r"status_code=status\.HTTP_(\d+)_")
_TOOL = re.compile(r'name="([a-z_]+)"')

_TITLES: dict[str, str] = {
    "access": "Access",
    "authority": "Authority",
    "counsel": "Counsel",
    "custody": "Custody",
    "equipment": "Equipment",
    "execution": "Execution",
    "pursuit": "Pursuit",
}


def _bounded_contexts() -> list[str]:
    return sorted(
        entry.name
        for entry in SRC.iterdir()
        if entry.is_dir()
        and not entry.name.startswith(("_", "."))
        and entry.name not in NON_BC
        and (entry / "__init__.py").exists()
    )


def _operations(bc: str) -> list[tuple[str, str, str, str]]:
    """Every operation in one context, as (method, path, tool, status)."""
    features = SRC / bc / "features"
    found: list[tuple[str, str, str, str]] = []
    for slice_dir in sorted(features.iterdir()):
        if not slice_dir.is_dir() or slice_dir.name.startswith("_"):
            continue
        route_file, tool_file = slice_dir / "route.py", slice_dir / "tool.py"
        if not route_file.exists() or not tool_file.exists():
            raise SystemExit(f"{bc}/{slice_dir.name} has no route.py or no tool.py")
        route = _ROUTE.search(route_file.read_text(encoding="utf-8"))
        tool = _TOOL.search(tool_file.read_text(encoding="utf-8"))
        if route is None or tool is None:
            raise SystemExit(f"{bc}/{slice_dir.name}: could not read its route or its tool name")
        status = _STATUS.search(route.group(3))
        found.append(
            (
                route.group(1).upper(),
                route.group(2),
                tool.group(1),
                status.group(1) if status else "200",
            )
        )
    return sorted(found, key=lambda row: (row[1], row[0]))


def render() -> str:
    contexts = _bounded_contexts()
    total = sum(len(_operations(bc)) for bc in contexts)
    lines = [
        "# The surface",
        "",
        "Every operation this system has, in one list.",
        "",
        "Each one is published twice, as an HTTP route and as an MCP tool, out of a",
        "single piece of code. A person and a machine reach the same model through the",
        "same rules, which is what makes granting a machine less than a person mean",
        "anything.",
        "",
        "**This page is generated.** `make docs-surface` rewrites it from the code, and a",
        "test regenerates it on every run and fails on any difference, so it cannot be",
        "out of date. Do not edit it by hand. What each operation means, and what it",
        "refuses, is on that context's own page.",
        "",
        f"{total} operations, across {len(contexts)} bounded contexts.",
        "",
    ]
    for bc in contexts:
        rows = _operations(bc)
        lines += [
            f"## {_TITLES.get(bc, bc.title())}",
            "",
            f"[What this context is for]({'bounded-contexts/' + bc + '.md'})",
            "",
            "| HTTP | MCP tool | On success |",
            "| --- | --- | --- |",
        ]
        lines += [f"| `{m} {p}` | `{t}` | `{s}` |" for m, p, t, s in rows]
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    rendered = render()
    if "--check" in sys.argv:
        current = PAGE.read_text(encoding="utf-8") if PAGE.exists() else ""
        if current != rendered:
            print(f"{PAGE} is out of date. Run: make docs-surface")
            return 1
        return 0
    PAGE.write_text(rendered, encoding="utf-8")
    print(f"wrote {PAGE.relative_to(APP_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
