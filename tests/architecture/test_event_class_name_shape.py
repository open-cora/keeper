"""Every event class name contains a past-participle token.

A domain event names what HAPPENED. The usual shape is the aggregate
followed by the participle:

    <Aggregate><PastParticiple>

The check is CONTAINS, not ENDS WITH, because three ordinary shapes put
the participle in the middle and something else last:

    <Aggregate><Participle><Status>       trailing discriminator
    <Aggregate><Participle><Preposition>  phrasal verb, split
    <Aggregate><Participle>To<Sibling>    trailing sibling noun

Ending-anchored, each of those reads as a violation, and the rule would
get relaxed rather than obeyed.

Recognised participle endings are -ed and -en. Deliberately NOT -ld: too
many ordinary English nouns and verbs end that way (Build, Field, Shield,
Yield, Guild, Child, Mold, Fold, Hold, Gold, Bold, Cold), so accepting it
as a suffix would wave through names that say nothing about what
happened. Genuine irregular participles are listed one at a time in
`_IRREGULAR_PARTICIPLES` instead, which is the slower and safer way to
widen a stemmer.

Scope is the aggregate's event union, not every class in the module.
A value object declared alongside the events is not an event and is not
named like one.
"""

import ast
import re
from collections.abc import Iterable
from pathlib import Path

import pytest

from tests.architecture.conftest import KEEPER_ROOT, tracked_python_files

pytestmark = pytest.mark.architecture

_PARTICIPLE_SUFFIXES: frozenset[str] = frozenset({"ed", "en"})

_IRREGULAR_PARTICIPLES: frozenset[str] = frozenset(
    {"Bound", "Done", "Held", "Made", "Set", "Unbound", "Withdrawn"}
)
"""Past participles that no suffix rule reaches.

English, not local vocabulary: these are the participles of bind, do,
hold, make, set, unbind and withdraw. Extend one at a time when an event
legitimately picks up another irregular form, never by loosening the
suffix rule.
"""

_TOKEN_RE = re.compile(r"[A-Z][a-z]*")


def _events_files() -> list[Path]:
    """Tracked events modules sitting inside an aggregate folder."""
    return sorted(
        path
        for path in tracked_python_files()
        if path.stem == "events" and "aggregates" in path.parts
    )


def _qualified(p: Path) -> str:
    return "keeper." + ".".join(p.relative_to(KEEPER_ROOT).with_suffix("").parts)


def _is_participle_token(token: str) -> bool:
    if token in _IRREGULAR_PARTICIPLES:
        return True
    return any(token.endswith(suffix) for suffix in _PARTICIPLE_SUFFIXES)


def _contains_participle(name: str) -> bool:
    return any(_is_participle_token(t) for t in _TOKEN_RE.findall(name))


def _event_union_members(tree: ast.AST) -> set[str]:
    """Class names appearing in any union alias whose name ends in Event.

    Recognises the pipe form and the subscript form, under a plain
    assignment, an annotated assignment, or a type alias statement.
    Returns nothing when the module declares no union, which a caller
    treats as out of scope rather than as a pass.
    """
    members: set[str] = set()

    def _flatten(node: ast.expr) -> Iterable[str]:
        if isinstance(node, ast.Name):
            yield node.id
        elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
            yield from _flatten(node.left)
            yield from _flatten(node.right)
        elif isinstance(node, ast.Subscript):
            slice_node = node.slice
            if isinstance(slice_node, ast.Tuple):
                for elt in slice_node.elts:
                    yield from _flatten(elt)
            else:
                yield from _flatten(slice_node)

    for node in ast.iter_child_nodes(tree):
        target_name: str | None = None
        value: ast.expr | None = None
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name):
                target_name = target.id
                value = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            target_name = node.target.id
            value = node.value
        elif isinstance(node, ast.TypeAlias):
            target_name = node.name.id
            value = node.value
        if target_name and target_name.endswith("Event") and value is not None:
            members.update(_flatten(value))
    return members


def test_the_event_name_scan_finds_at_least_one_aggregate() -> None:
    """Guard the enumeration: an empty parameter set skips, it does not fail."""
    assert _events_files(), (
        "No events module found inside any aggregate folder, so the past-tense "
        "rule below ran against nothing."
    )


@pytest.mark.parametrize("path", _events_files(), ids=_qualified)
def test_every_event_in_the_union_is_named_in_the_past_tense(path: Path) -> None:
    tree = ast.parse(path.read_text())
    members = _event_union_members(tree)
    if not members:
        pytest.skip(f"{_qualified(path)} declares no event union")
    offenders = sorted(name for name in members if not _contains_participle(name))
    assert not offenders, (
        f"{_qualified(path)} declares event class(es) with no past-participle "
        "token:\n  "
        + "\n  ".join(offenders)
        + "\n\nAn event records what happened, so its name is in the past tense. "
        "Split the class name into its capitalised tokens: at least one must end "
        "in -ed or -en, or be a listed irregular participle. If the name is right "
        "and the participle is a form this check does not know, add it to "
        "_IRREGULAR_PARTICIPLES with the verb it comes from."
    )
