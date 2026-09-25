"""Every slice directory names a subject, not just a verb.

Slice directories follow `<verb>_<subject>[_<qualifier>]`. The subject
names what the slice acts on. A bare verb tells a reader that something
happens without saying to what, and a directory named that way is almost
always a slice that belongs somewhere other than a bounded context's
features/ folder.

The set of recognised subjects is DERIVED from the tree: every aggregate
folder under any bounded context, plus its regular plural forms for the
list-style query slices. Nothing is hand-listed, so a new aggregate is
recognised the moment it exists rather than when someone remembers to
extend a tuple.

That derivation is the check's independent side. A slice name and an
aggregate folder name are written in two different places by two
different acts, so agreement between them is evidence. The rule catches
a slice naming a subject the codebase does not have, which is what a
typo and a bare verb both look like.

`_DOMAIN_NOUN_ALLOWLIST` is for a subject that is a persisted value type
rather than an aggregate, so no folder exists to derive it from. An
entry belongs in docs/reference/conventions.md as well, since it widens
the vocabulary the rule accepts, and a hand-written subject is exactly
the kind that drifts from the code once nothing derives it.
"""

from collections.abc import Iterable
from functools import cache
from pathlib import Path

import pytest

from tests.architecture.conftest import KEEPER_ROOT, discovered_bcs, tracked_python_files

pytestmark = pytest.mark.architecture

_DOMAIN_NOUN_ALLOWLIST: frozenset[str] = frozenset({"permission", "step"})
"""Subjects that name a persisted value type rather than an aggregate.

Two entries. `permission` is a pair stored inside a Policy and `step` is
one element of the list an Execution fixes at its genesis. Neither has an
aggregate folder, and neither can: a permission has no id, and a step is
identified by its place in an execution rather than by anything of its own.

Add another only when the subject is real and cannot be derived from the
tree, and document it alongside the other naming rules so the vocabulary
stays written down in one place.
"""


@cache
def _aggregate_names() -> frozenset[str]:
    """Aggregate folder names across every bounded context, from tracked files.

    Derived from git-tracked paths rather than a directory execution, so an
    untracked work-in-progress aggregate is invisible here in the same way
    it is invisible to pre-commit.
    """
    names: set[str] = set()
    for path in tracked_python_files():
        parts = path.parts
        for index, part in enumerate(parts):
            if part == "aggregates" and index + 1 < len(parts) - 1:
                names.add(parts[index + 1])
    return frozenset(names)


@cache
def _known_subjects() -> frozenset[str]:
    return _aggregate_names() | _DOMAIN_NOUN_ALLOWLIST


def _plural_to_singular(token: str) -> str:
    """Map the regular English plural forms back to the singular."""
    if token.endswith("ies") and len(token) > 4:
        return token[:-3] + "y"
    if token.endswith("ches") or token.endswith("shes"):
        return token[:-2]
    if token.endswith("s") and len(token) > 1 and not token.endswith("ss"):
        return token[:-1]
    return token


@cache
def _slice_dirs() -> list[Path]:
    """Every tracked slice directory under any bounded context's features/."""
    dirs: set[Path] = set()
    for bc in discovered_bcs():
        features = KEEPER_ROOT / bc / "features"
        for path in tracked_python_files():
            if path.parent.parent != features:
                continue
            if path.parent.name.startswith("_"):
                continue
            dirs.add(path.parent)
    return sorted(dirs)


def _slice_id(p: Path) -> str:
    return p.parent.parent.name + "." + p.name


def test_the_subject_scan_finds_at_least_one_slice_and_one_aggregate() -> None:
    """Guard both sides: either side empty makes the comparison meaningless.

    An empty slice list skips the rule below. An empty aggregate set is
    worse: the rule would run and fail every slice, which looks like a
    naming problem rather than a broken derivation.
    """
    assert _slice_dirs(), "No slice directory found under any bounded context."
    assert _aggregate_names(), (
        "No aggregate folder found under any bounded context, so the derived "
        "subject vocabulary is empty and every slice name would be rejected."
    )


def _stale_noun_entries(
    allowlist: Iterable[str], aggregates: Iterable[str], slice_names: Iterable[str]
) -> list[str]:
    """Allowlisted nouns that no longer earn their place, with the reason.

    Two ways to go stale, opposite to each other. A noun an aggregate
    now provides is redundant: `_known_subjects` would accept it either
    way, so the entry reads as a standing decision about a word the tree
    already supplies. A noun no slice uses is dead weight, and dead
    weight in a vocabulary list is what lets the vocabulary drift from
    the names actually in use.

    Takes all three sets as arguments so the check can be run against
    inputs of the caller's choosing. Nothing in this repository is stale,
    so neither branch fires against the real allowlist and both are
    exercised below against inputs that do.
    """
    aggregate_set = set(aggregates)
    used = {_plural_to_singular(token) for name in slice_names for token in name.split("_")} | {
        token for name in slice_names for token in name.split("_")
    }
    stale: list[str] = []
    for noun in sorted(allowlist):
        if noun in aggregate_set:
            stale.append(
                f"{noun}: an aggregate folder now provides this subject, so the entry adds nothing."
            )
        elif noun not in used:
            stale.append(f"{noun}: no slice directory names this subject.")
    return stale


def test_no_allowlisted_noun_is_redundant_or_unused() -> None:
    """Drift catcher: the vocabulary list must not outlive the names in it.

    `_DOMAIN_NOUN_ALLOWLIST` is the one allowlist here that had no drift
    check. An entry survived a rename or an aggregate landing under the
    same name with nothing to notice.
    """
    stale = _stale_noun_entries(
        _DOMAIN_NOUN_ALLOWLIST, _aggregate_names(), [d.name for d in _slice_dirs()]
    )
    assert not stale, "_DOMAIN_NOUN_ALLOWLIST entries to prune:\n  " + "\n  ".join(stale)


def test_the_drift_catcher_reports_a_redundant_or_unused_noun() -> None:
    """Run the catcher over entries that are stale, because none here is."""
    aggregates = {"actor"}
    slice_names = ["register_actor", "archive_gadget"]

    assert _stale_noun_entries(["gadget"], aggregates, slice_names) == []

    (redundant,) = _stale_noun_entries(["actor"], aggregates, slice_names)
    assert "an aggregate folder now provides" in redundant

    (unused,) = _stale_noun_entries(["widget"], aggregates, slice_names)
    assert "no slice directory names" in unused


@pytest.mark.parametrize("slice_dir", _slice_dirs(), ids=_slice_id)
def test_a_slice_directory_name_carries_a_known_subject(slice_dir: Path) -> None:
    bc = slice_dir.parent.parent.name
    qualified = f"keeper.{bc}.features.{slice_dir.name}"
    known = _known_subjects()
    tokens = slice_dir.name.split("_")
    if any(_plural_to_singular(token) in known or token in known for token in tokens):
        return
    pytest.fail(
        f"{qualified} names no recognised subject.\n"
        f"  tokens:            {tokens}\n"
        f"  known aggregates:  {sorted(_aggregate_names())}\n"
        f"  allowlisted nouns: {sorted(_DOMAIN_NOUN_ALLOWLIST)}\n\n"
        "A slice directory is <verb>_<subject>[_<qualifier>]. The subject names "
        "the aggregate the slice acts on, not just the verb's grammatical object. "
        "If the subject is a persisted value type with no aggregate of its own, "
        "add it to _DOMAIN_NOUN_ALLOWLIST here and to the naming rules in "
        "docs/reference/conventions.md. Otherwise carry the subject into the "
        "slice, command and tool names together."
    )
