"""Every bounded-context page answers the same questions, in the same order.

Seven pages describe seven contexts, and before this rule existed they
shared almost nothing. Seventy of the eighty-two distinct section
headings across them appeared on exactly one page, so a reader who
learned to navigate one could not navigate the next. Two pages never said
what their aggregate was made of, two never said what gets refused, and
one of those carried none of the closing sections either and opened on an
argument about a decision the reader had not yet been told about.

The cure is not a template. The rationale sections are the best writing
in these pages and every context earned different ones, so nothing here
touches them. What is fixed is the frame around them: a reader meets the
noun first, finds the operations in a table, then what is stored, what is
refused, where the code is, and what is missing, on every page.

## The operations check, which is why this file exists at all

A required heading that is present and wrong is worse than one that is
absent, so the operations section is checked for content as well.

`execution.md` said "fourteen operations" in three places over a table of
thirteen rows, matching thirteen slices on disk. It had been wrong for as
long as anyone had been reading it, because a count written into prose is
compared against nothing. The page beside it said "five operations" in
its opening line and "The four operations" in its own heading.

So the counts came out of the headings, and this compares the table
against the tree instead. A slice added without a row fails here, which
is the case that used to pass, and a row naming a tool no slice provides
fails too, which is the case a reader meets as a 404.
"""

import re

import pytest

from tests._roots import APP_ROOT
from tests.architecture.conftest import discovered_bcs, discovered_slices

pytestmark = pytest.mark.architecture

_PAGES = APP_ROOT / "docs" / "bounded-contexts"

_H2 = re.compile(r"(?m)^## (.+)$")

_TOOL_CELL = re.compile(r"(?m)^\|[^|]*\|[^|]*\|\s*`([a-z_]+)`\s*\|")
"""The MCP tool named in the third cell of an operations-table row.

The third cell rather than the first, because a tool name is the one cell
that has to match something in the tree exactly. What an operation does is
prose, and a route can be spelled several defensible ways.
"""

_REQUIRED: tuple[tuple[str, str], ...] = (
    ("what the aggregate is", r"^What an? .+ is$"),
    ("the operations", r"^The operations\b"),
    ("what the stream holds", r"^What the streams? holds?$"),
    ("what gets refused", r"^What gets refused$"),
    ("where the code is", r"^Where the code is$"),
    ("what is not here yet", r"^What is not here yet$"),
)
"""The sections every context page carries, and how each is recognised.

Loose where a page has a real reason to differ. A context holding three
aggregates opens with three `What a ... is` sections and calls its stored
events "streams", and both read correctly, so the patterns admit them.
Counsel's two aggregates each take an `The operations on a ...` heading,
which is why that one matches a prefix rather than the whole line.
"""

_LAST = "What is not here yet"
"""The section that closes every page.

Last rather than merely present. What a context has not built is the
question a reader arrives with least often and leaves with most, and a
page that buries it mid-way invites the reader to stop before it.
"""


def _headings(bc: str) -> list[str]:
    return _H2.findall((_PAGES / f"{bc}.md").read_text(encoding="utf-8"))


def _page_names() -> list[str]:
    """Contexts that have a page. Authority was the last one without."""
    return [bc for bc in discovered_bcs() if (_PAGES / f"{bc}.md").exists()]


def test_the_scan_finds_a_page_for_every_bounded_context() -> None:
    """Guard the derivation: a rule ranging over nothing passes vacuously.

    The other checks here are parametrized over the pages that exist, so a
    context whose page was never written would be checked by none of them
    and the run would still be green.
    """
    missing = sorted(set(discovered_bcs()) - set(_page_names()))
    assert discovered_bcs(), "No bounded context was discovered, so nothing below ran."
    assert not missing, (
        "These bounded contexts have no page under docs/bounded-contexts/:\n  "
        + "\n  ".join(missing)
        + "\n\nEvery check in this file is parametrized over the pages that "
        "exist, so an unwritten one is invisible to all of them."
    )


@pytest.mark.parametrize("bc", _page_names())
def test_a_context_page_carries_every_required_section(bc: str) -> None:
    headings = _headings(bc)
    missing = [
        name for name, pattern in _REQUIRED if not any(re.match(pattern, h) for h in headings)
    ]
    assert not missing, (
        f"docs/bounded-contexts/{bc}.md is missing: {', '.join(missing)}.\n\n"
        "Every context page answers the same questions in the same order, so "
        "a reader who has read one can navigate the rest. The sections between "
        "them are free and should stay that way."
    )


@pytest.mark.parametrize("bc", _page_names())
def test_a_context_page_introduces_its_aggregate_before_arguing_about_it(bc: str) -> None:
    headings = _headings(bc)
    assert headings, f"docs/bounded-contexts/{bc}.md has no sections at all."
    assert re.match(_REQUIRED[0][1], headings[0]), (
        f"docs/bounded-contexts/{bc}.md opens on {headings[0]!r}.\n\n"
        "The first section says what the aggregate is made of. A page that "
        "opens on why a decision was taken asks the reader to follow an "
        "argument about something they have not been shown."
    )


@pytest.mark.parametrize("bc", _page_names())
def test_a_context_page_ends_on_what_it_has_not_built(bc: str) -> None:
    headings = _headings(bc)
    assert headings and headings[-1] == _LAST, (
        f"docs/bounded-contexts/{bc}.md ends on "
        f"{headings[-1] if headings else 'nothing'!r} rather than {_LAST!r}."
    )


@pytest.mark.parametrize("bc", _page_names())
def test_a_context_page_lists_the_operations_the_code_actually_has(bc: str) -> None:
    page = (_PAGES / f"{bc}.md").read_text(encoding="utf-8")
    listed = set(_TOOL_CELL.findall(page))
    built = {
        slice_name.split("/", 1)[1]
        for slice_name in discovered_slices()
        if slice_name.startswith(f"{bc}/")
    }

    undocumented = sorted(built - listed)
    invented = sorted(listed - built)
    assert not undocumented and not invented, (
        f"docs/bounded-contexts/{bc}.md and src/keeper/{bc}/features/ disagree.\n"
        + (f"  Built and not on the page: {', '.join(undocumented)}\n" if undocumented else "")
        + (f"  On the page and not built: {', '.join(invented)}\n" if invented else "")
        + "\nA slice with no row is an operation a reader cannot find. A row "
        "with no slice is a 404 the page promised."
    )


def test_the_tool_scan_reads_a_table_and_ignores_ordinary_prose() -> None:
    """Both halves matter, and the second is how this rule dies quietly.

    A pattern that stopped matching table rows would report every page as
    complete, because an empty set of listed tools and an empty set of
    built slices differ by nothing only when both are empty, and the first
    check above is the only thing that would notice.
    """
    table = (
        "| What it does | HTTP | MCP tool | On success |\n"
        "| --- | --- | --- | --- |\n"
        "| Add one | `POST /things` | `register_thing` | `201` |\n"
        "| Read one | `GET /things/{id}` | `get_thing` | `200` |\n"
        "\nProse mentioning `register_thing` outside a table, and a | pipe.\n"
    )
    assert set(_TOOL_CELL.findall(table)) == {"register_thing", "get_thing"}
