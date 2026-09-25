"""Source may not name the sibling project.

This repository's chassis was copied once from a sibling project and is owned
outright from that point on. CLAUDE.md bans provenance comments pointing at
that tree, and when this file was written source named it twice, to say what
its kernel carries and what it names its tracer. Prose explaining this tree by
describing that one costs a reader a search that ends in nothing, which is the
same defect `test_docstring_references_resolve.py` next door was built for.

## Why this is a separate rule from that one

That rule resolves a name against the tree, which requires the name to look
like a name: backticked, and shaped like an identifier. What came across was
not always either. `CORA names its tracer after the first BC` is ordinary
prose with an ordinary capital, and no resolution rule reaches it without
flagging every sentence that starts with a word. A closed list does reach it,
at the cost of only catching what is listed.

So read the two together: the rule next door is general and shape-bound, this
one is shape-blind and specific. Neither subsumes the other.

## The domain nouns that used to be here, and why they went

A second tier once sat beside the project's name, holding the sibling's
facility vocabulary and three of its aggregates. It was added because copied
docstrings really did carry those words, and it was a cleanup aid for prose
that was present rather than a promise this project would never use them. The
cleanup is long done and the tier is retired. Recording why, so that nobody
reads its absence as an oversight and puts it back:

  - `equipment` went first, because this project came to model it.
    `keeper.equipment` holds the Device aggregate, and the word arrived from a
    question about what a beamline's hardware register should be called rather
    than from the sibling tree.
  - `procedure` went for the same reason. `apps/conductor` composes a
    procedure, and the word arrived from a question about what to call that.
    Two projects reaching the same ordinary noun for the same real thing is
    convergence, and the ban exists to stop inheritance.
  - `recipe` went for the opposite reason. Nothing here models one and no page
    here said the word, so its only occurrences in this repository were in the
    file banning it. A rule whose whole effect is to make the tree say a word
    it would not otherwise say is not paying for itself.
  - `beam`, `clearance` and `enclosure` went because this is a facility
    project too. They were kept when `capture`, `supply` and `allocation` were
    let go, on the grounds that those three were ordinary English here and
    these three were not. That was wrong: at a synchrotron a beam is the most
    ordinary noun there is. `apps/reporter` had already written `beam` five
    times, as a message prefix in fixtures, and the tree stayed green only
    because this scan is rooted at `apps/keeper`.

The test that scans the tree cannot tell a domain use from an innocent one, so
the standing rule is the one those removals converge on: a word earns a place
here only if it has no other meaning in this codebase. That is what makes a
hit worth acting on rather than worth excepting, and the sibling's own name is
the clearest case of it.

## What this does not reach

`_scanned_files` enumerates `apps/keeper` and stops there. A docstring in
`apps/reporter` or `apps/conductor` may name the sibling and nothing here
notices, and those are the newest Python in the tree and a plausible place for
a provenance comment to appear. Nothing does today, checked rather than
assumed, so widening would go green on the first run.

It is still not this file's to do alone. The same enumerator feeds the em
dash, emoji and product-name checks, which stop in the same place, so one of
the four reaching further would trade a known gap for an inconsistent one. And
it crosses a line the tree drew deliberately: the client apps build and ship
separately, each with its own lanes, and a check here that failed on their
source would make one project's suite red for another project's file. Whoever
widens the tier decides that for the family, not for this rule.

## Whether one word is worth a file

With the domain tier retired this list holds a single word, and a list of one
invites the question. The answer is yes for now, and the reason is not the
length of the list. CLAUDE.md's ban on provenance comments is a live rule,
nothing else enforces it, and the two occurrences this file was written to
remove were real rather than hypothetical.

The machinery is sized for more terms than it holds, which is the cost of
that answer and also what keeps adding one back cheap. So retiring this file
is a decision about whether the ban is still worth enforcing, and not one
about how short the list has become.
"""

import re
from pathlib import Path

import pytest

from tests.architecture.conftest import REPO_ROOT, tracked_python_files, tracked_test_files

pytestmark = pytest.mark.architecture

SIBLING_PROJECT_TERMS: frozenset[str] = frozenset(
    {
        # The project itself, which CLAUDE.md bans source from pointing at.
        # Both mentions that were here explained this tree by describing that
        # one, which is the habit the ban exists to stop.
        "cora",
        # The domain tier that used to sit here is retired. The module
        # docstring records all six words and why each one went.
    }
)
"""Words with no other meaning in this codebase than the sibling's use of them.

That is the whole bar, and the module docstring records the six words that
failed it. A term earns a place only if a hit on it is a defect rather than a
candidate for an exception, which in practice means the sibling's own name.

Adding a domain noun back needs an argument that it is unsayable here for any
innocent reason, and the history above is six demonstrations that such an
argument is harder to make than it looks.
"""

_TERM_PATTERN = re.compile(rf"\b(?:{'|'.join(sorted(SIBLING_PROJECT_TERMS))})s?\b", re.IGNORECASE)

_THIS_FILE = "test_no_sibling_project_vocabulary.py"


def find_terms(text: str) -> list[tuple[int, str]]:
    """Every line of `text` carrying a listed term, as (line number, line).

    Takes the text rather than a path so the check below can be run against
    input of the caller's choosing, which is the only way to show it fires.
    """
    return [
        (number, line.strip())
        for number, line in enumerate(text.splitlines(), start=1)
        if _TERM_PATTERN.search(line)
    ]


def _scanned_files() -> list[Path]:
    """Tracked source and test files, minus this one.

    This file has to name what it refuses, so scanning it would fail on its
    own list.
    """
    return sorted(
        path for path in tracked_python_files() | tracked_test_files() if path.name != _THIS_FILE
    )


def test_the_vocabulary_scan_covers_the_tree() -> None:
    """Guard the enumeration: an empty file set makes the rule below vacuous."""
    assert _scanned_files(), "No tracked source file found, so the scan below reads nothing."


def test_the_scanner_finds_a_term_and_leaves_ordinary_prose_alone() -> None:
    """Run the scanner over text of this test's choosing, since the tree is clean.

    The second half matters as much as the first. A scanner keyed on
    substrings rather than words would hit `decorator`, which a Python
    codebase says constantly, and a rule that fires on ordinary prose gets
    excepted into uselessness.

    Every example here is built from a term that is still listed. One built
    from a term that has been retired still passes, because the assertion is
    on the line rather than on which term matched, so it would go green while
    reading as though it guarded something. That is how this file would go
    quietly vacuous, and it is why removing a term means coming through here.
    """
    hits = find_terms("CORA names its tracer after the first BC\nand a clean line\n")
    assert hits == [(1, "CORA names its tracer after the first BC")]

    assert find_terms("the cora kernel carries a tenant id")

    assert not find_terms("a decorator, some coral, and corallary reasoning")


@pytest.mark.parametrize("term", sorted(SIBLING_PROJECT_TERMS))
def test_every_listed_term_is_one_the_scanner_would_catch(term: str) -> None:
    """Guard the pattern build: a term the regex cannot express is not enforced."""
    assert find_terms(f"a line about {term} here") == [(1, f"a line about {term} here")]


def test_no_source_file_names_the_sibling_project_or_its_vocabulary() -> None:
    offenders: list[str] = []
    for path in _scanned_files():
        for number, line in find_terms(path.read_text(encoding="utf-8")):
            offenders.append(f"{path.relative_to(REPO_ROOT)}:{number}: {line}")

    assert not offenders, (
        "Source names the sibling project or something only it models:\n  "
        + "\n  ".join(offenders)
        + "\n\nThe chassis is owned outright here, so prose explaining it should "
        "describe this tree rather than the one it was copied from. If the word "
        "has a use here that is nothing to do with the sibling, whether because "
        "this project came to model the thing or because it is ordinary English, "
        "drop it from SIBLING_PROJECT_TERMS in the same commit, say why, and "
        "check the examples in this file that were built from it."
    )


def test_every_listed_term_is_a_plain_lowercase_word() -> None:
    """A term carrying punctuation would silently rewrite the alternation.

    The pattern joins the list with `|` inside a group, so a term containing
    a regex metacharacter would change what every other term matches rather
    than just failing on its own.
    """
    malformed = sorted(
        term for term in SIBLING_PROJECT_TERMS if not term.isalpha() or not term.islower()
    )
    assert malformed == [], (
        f"SIBLING_PROJECT_TERMS entries must be plain lowercase words: {malformed}"
    )
