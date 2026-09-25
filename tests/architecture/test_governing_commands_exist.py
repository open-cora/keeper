"""A policy's governing commands are commands something can actually issue.

`GOVERNING_COMMAND_NAMES` on the Policy aggregate is the rule that stops
a rulebook being left unchangeable: a policy must permit someone to
issue each of those commands. The names are strings, written in the
aggregate, and the commands they refer to are declared somewhere else
entirely, as the `_COMMAND_NAME` literal in a slice handler.

Nothing about writing a string in two files makes them agree. If the
grant slice were renamed and the aggregate not updated, the rule would
require a permission for a command nobody can send. Every policy would
still have to carry it, no caller could ever use it, and the guard would
go on reporting that the policy was governable while nothing could
change it. That failure is silent in both directions: the rule still
passes, and the command still works.

The two sides are independent, which is what makes the comparison worth
running. One is a set an author declares as a domain rule. The other is
read from the handlers, where a command name exists because a slice
issues it. They are written in different files by different acts.

Scoped to the Authority context, which is the only one declaring
governing commands. A second context doing so extends the derivation
rather than this list.
"""

import ast

import pytest

from keeper.authority.aggregates.policy import GOVERNING_COMMAND_NAMES
from tests.architecture.conftest import KEEPER_ROOT, tracked_python_files

pytestmark = pytest.mark.architecture


def _declared_command_names() -> frozenset[str]:
    """Every `_COMMAND_NAME` literal declared by a slice handler.

    Read from the source rather than by importing, for the same reason
    the rest of this directory does: a name that exists only because an
    import happened to succeed is a weaker fact than one written down.
    """
    found: set[str] = set()
    for path in tracked_python_files():
        if path.name != "handler.py" or not path.is_relative_to(KEEPER_ROOT):
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Constant):
                continue
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "_COMMAND_NAME":
                    found.add(str(node.value.value))
    return frozenset(found)


def test_the_command_scan_finds_the_slices_it_ranges_over() -> None:
    """Guard the derivation: an empty scan would make the rule vacuous.

    The comparison below passes when nothing is missing, and an empty
    left-hand side produces exactly that. The floor is loose on purpose;
    it only has to be high enough that a scan which has stopped working
    cannot look like agreement.
    """
    found = _declared_command_names()
    assert len(found) >= 4, f"only {len(found)} command names found across every handler: {found}"


def test_every_governing_command_is_one_a_slice_actually_issues() -> None:
    declared = _declared_command_names()
    missing = GOVERNING_COMMAND_NAMES - declared
    assert not missing, (
        "The Policy aggregate requires a permission for commands no handler issues:\n  "
        + "\n  ".join(sorted(missing))
        + "\n\nEvery policy would have to carry a permission nobody can use, and the "
        "governance guard would keep reporting policies as changeable while nothing "
        "could change them. Either a slice was renamed without updating "
        "GOVERNING_COMMAND_NAMES, or a name was added to it ahead of the slice that "
        "issues it.\n"
        f"Commands handlers declare: {sorted(declared)}"
    )
