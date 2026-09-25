"""The domain and its docs name no particular product.

A run happens in whatever engine a deployment runs and its data lands in
whatever store a deployment keeps, and the two contexts here hold records
of what each one did. Which engine and which store are a deployment's
facts, not modelling ones: `Identifier`'s scheme half is open for exactly
that reason, and both state modules say so.

This began as a rule about engines and grew a second family when Custody
landed. The generalisation is the same claim, not a wider one: naming any
product a deployment might run turns a rule stated for one into a rule
that reads as derived from one.

Prose can leak what the types do not. Three sentences in the Execution
page justified domain rules by naming one engine, saying that it offers
three ways to stop a paused run, that its documents carry a timestamp, and
what it calls a cooperative pause. Every one of those was true and
load-bearing as evidence, and every one of them read as though the model
had been derived from a vendor.

## What is banned, and where

Documentation pages and the source tree. An engine name in either is a
claim, and the claim is wrong in the same way whether or not the fact
behind it is right: the rule holds for any engine, and naming one says a
second would need a second rule.

## Two families, and one of them needs a narrower match

The engine family is five unambiguous words. The store family is one word
that is also an ordinary English adjective, and a tiled array is a real
thing to write about in a tree that holds detector data.

Matching that one case-insensitively would fire on ordinary prose, and
this file's own warning below says what happens next: a rule that fires on
prose gets excepted into uselessness. So an ambiguous term is matched as a
PROPER NOUN, capitalised, and left alone in lower case.

That trade is deliberate and it is not free. A capitalised match catches
every ordinary way a product gets named in prose, because people
capitalise product names, and it misses a sentence that spells one in
lower case. The residual hole is smaller than the one a case-insensitive
match would open, and unlike that one it does not grow every time somebody
writes about an array.

## What is not banned, and why each is different

**The clients.** `apps/reporter` speaks to one acquisition engine and one
store, and `apps/conductor` drives one control protocol, so each of them
names its own products freely. Engine facts belong on the adapter side of
a port, and those packages are that side.

They are outside the scanned set by construction rather than by
exception: the two enumerators below reach `src/keeper` and `docs` and
nothing else.
Widening either one is the moment to add a real exclusion, and until then
an exclusion here would be a filter that has never removed anything.

**The beamline page.** It used to live under this project's `docs/` and
needed an exclusion by name, because which engine and which control system a
beamline runs are the whole of what such a page is for. It now sits with the
descriptors it describes, outside this project, so the exclusion went with
it. Removing it was not a decision: the guard that asked whether it still
filtered anything failed the moment the page moved, which is what that kind
of guard is for.

**Test data.** Tests pass a scheme string like an engine's name into an
open-scheme field, which is a value rather than an assertion. A test
needs some concrete string and a realistic one reads better than a
placeholder, and nothing about it says the model assumes that engine.

This is the difference from `test_no_sibling_project_vocabulary.py` next
door, which scans tests as well: that rule bans a vocabulary, a word
meaning something only in a tree this one does not model, so a hit
anywhere is a defect. This rule bans a claim, and data makes none.

**Design precedents, but only for products nothing here runs.** Naming
Temporal or Step Functions as the shape somebody else settled on is a
citation rather than an assumption, because no deployment of this system
runs either.

That exemption does not survive a product moving into the listed set, and
the store is what proved it. `infrastructure/auth/config.py` cited that
store by name as the precedent for holding two subject mappers, which read
as a neutral citation for as long as nothing here kept data anywhere. With
a context whose whole job is recording which store holds what, the same
sentence reads as a nod to the one this deployment uses. It was rewritten
to say the same thing without the name when this rule grew its second
family, and the substance survived the edit intact, which is the usual
outcome and the reason the rule is cheap.
"""

import re
from pathlib import Path

import pytest

from tests.architecture.conftest import (
    REPO_ROOT,
    tracked_markdown_files,
    tracked_python_files,
)

pytestmark = pytest.mark.architecture

PRODUCT_TERMS: frozenset[str] = frozenset(
    {
        # The engine the first reporter speaks to, and the three projects
        # around it that a reader would take for the same claim.
        "bluesky",
        "ophyd",
        "databroker",
        "runengine",
        # The control system underneath it. Less likely to be reached for
        # and more damaging if it is, because a control system is further
        # from anything these contexts model than the engine is.
        "epics",
        # A second engine, which a spike drove to find out whether the run
        # model was general or only well named. Listed for the same reason
        # the first one is, and more urgently: a page arguing from two
        # engines is likelier to want to name them.
        "tomoscan",
        # The store Custody's first reporter writes to. Also an ordinary
        # English word, so it is matched as a proper noun; see below.
        "tiled",
    }
)
"""Product names a domain page or a source file may not use.

An entry earns its place by naming a particular product this deployment
might run, rather than a kind of thing the model is about. Removing one
would mean this project had decided to model that product, which is a
decision worth making on purpose and against the layering.
"""

ALSO_ORDINARY_ENGLISH: frozenset[str] = frozenset({"tiled"})
"""Listed products that are ordinary English words as well as names.

Matched only in their capitalised form. A word in here is one where a
case-insensitive match would fire on prose that makes no claim at all, and
the module docstring above argues the trade.

Every entry must also appear in `PRODUCT_TERMS`. This set narrows how a
term is matched; it never adds one, and a test below is what keeps that
true.
"""


def _pattern(terms: frozenset[str], *, ignore_case: bool) -> re.Pattern[str] | None:
    """One alternation over `terms`, or None when there are none to match."""
    if not terms:
        return None
    flags = re.IGNORECASE if ignore_case else 0
    return re.compile(rf"\b(?:{'|'.join(sorted(terms))})\b", flags)


_PLAIN_PATTERN = _pattern(PRODUCT_TERMS - ALSO_ORDINARY_ENGLISH, ignore_case=True)
_PROPER_NOUN_PATTERN = _pattern(
    frozenset(term.capitalize() for term in ALSO_ORDINARY_ENGLISH), ignore_case=False
)

_THIS_FILE = "test_the_domain_names_no_product.py"


def find_products(text: str) -> list[tuple[int, str]]:
    """Every line of `text` naming a listed product, as (line number, line).

    Takes the text rather than a path so the checks below can be shown to
    fire against input of the caller's choosing, the tree being clean.

    Two patterns rather than one, because the two families are matched
    differently and a single alternation cannot carry two case rules.
    """
    patterns = [
        pattern for pattern in (_PLAIN_PATTERN, _PROPER_NOUN_PATTERN) if pattern is not None
    ]
    return [
        (number, line.strip())
        for number, line in enumerate(text.splitlines(), start=1)
        if any(pattern.search(line) for pattern in patterns)
    ]


def _scanned_files() -> list[Path]:
    """Tracked source and documentation, minus this file.

    This file has to name what it refuses, so scanning it would fail on
    its own list. Nothing else is excluded: the one subtree that was, the
    beamline pages, no longer sits in this project.
    """
    return sorted(
        path
        for path in tracked_python_files() | tracked_markdown_files()
        if path.name != _THIS_FILE
    )


def test_the_product_scan_covers_source_and_documentation() -> None:
    """Guard the enumeration: an empty file set makes the rule vacuous."""
    scanned = _scanned_files()
    assert any(path.suffix == ".py" for path in scanned), "No source file scanned."
    assert any(path.suffix == ".md" for path in scanned), "No documentation scanned."


def test_the_scanner_finds_a_product_and_leaves_ordinary_prose_alone() -> None:
    """The second half matters as much as the first. A scanner keyed on
    substrings would hit `blueskies` and any word ending in `epic`, and a
    rule that fires on ordinary prose gets excepted into uselessness."""
    hits = find_products("as Bluesky does it\nand a clean line\n")
    assert hits == [(1, "as Bluesky does it")]

    assert find_products("the EPICS record underneath")
    assert not find_products("blueskies epically ophydia runengines_plural")


def test_an_ambiguous_term_is_caught_as_a_name_and_left_alone_as_a_word() -> None:
    """The whole reason the store family is matched differently.

    Both halves are load-bearing. Missing the first would let the rule
    this file exists for be broken by writing a product name. Failing the
    second would make every sentence about a tiled array a CI failure,
    and a tree holding detector data has reason to write one.
    """
    assert find_products("the same pattern Tiled uses") == [(1, "the same pattern Tiled uses")]
    assert find_products("Tiled's catalog")

    assert not find_products("a tiled detector array")
    assert not find_products("the readings are tiled across four modules")


@pytest.mark.parametrize("term", sorted(PRODUCT_TERMS))
def test_every_listed_product_is_one_the_scanner_would_catch(term: str) -> None:
    """Guard the pattern build: a term the regex cannot express is unenforced.

    An ambiguous term is probed in the form it is actually matched in,
    because probing the lower-case form would assert the opposite of what
    that family is for and this guard would then demand the bug.
    """
    spelling = term.capitalize() if term in ALSO_ORDINARY_ENGLISH else term
    line = f"a line about {spelling} here"
    assert find_products(line) == [(1, line)]


def test_every_term_matched_as_a_proper_noun_is_also_a_listed_product() -> None:
    """Guard the second set: it narrows a match, it never adds one.

    An entry here that `PRODUCT_TERMS` does not carry would be matched by
    the scanner and described by nothing, so a reader auditing the list
    would not find it.
    """
    unlisted = sorted(ALSO_ORDINARY_ENGLISH - PRODUCT_TERMS)
    assert unlisted == [], (
        f"Matched as proper nouns but not listed as products: {unlisted}. "
        "ALSO_ORDINARY_ENGLISH narrows how a listed term is matched; every "
        "entry must also appear in PRODUCT_TERMS."
    )


def test_no_source_or_docs_file_names_a_particular_product() -> None:
    offenders: list[str] = []
    for path in _scanned_files():
        for number, line in find_products(path.read_text(encoding="utf-8")):
            offenders.append(f"{path.relative_to(REPO_ROOT)}:{number}: {line}")

    assert not offenders, (
        "Source or documentation names a particular product:\n  "
        + "\n  ".join(offenders)
        + "\n\nWhich engine a deployment runs and which store it keeps data in "
        "are a deployment's facts, so a rule stated for one reads as a rule "
        "derived from one. Say what holds for any of them, and keep what only "
        "one does in the client package that speaks to it, or on a beamline "
        "page beside the descriptors."
    )


def test_every_listed_product_is_a_plain_lowercase_word() -> None:
    """A term carrying punctuation would silently rewrite the alternation.

    The pattern joins the list with `|` inside a group, so a term holding a
    regex metacharacter would change what every other term matches rather
    than failing on its own. Lower case is also what `_pattern` assumes
    when it capitalises the ambiguous family.
    """
    malformed = sorted(term for term in PRODUCT_TERMS if not term.isalpha() or not term.islower())
    assert malformed == [], f"PRODUCT_TERMS entries must be plain lowercase words: {malformed}"
