"""A command that names a beamline is authorized against that beamline.

`Permission` carries a beamline, and `authorize` takes one, and neither
can make a handler supply it. A handler that resolves a beamline and
asks without it asks a narrower question than it should: it is answered
against the permissions for nowhere, which fails closed, so the symptom
is a caller refused for no visible reason rather than one admitted.

The two sides here are independent, which is what makes the comparison
worth running. One is a field an author put on a command because the
domain has a place in it. The other is an argument a handler passes.
Nothing but this connects them, and the connection is exactly the kind
this tree keeps finding rotted: a rule that holds in four files on the
day it is written and in three a month later.

## What it does not reach

A command that resolves a beamline by reading another aggregate rather
than carrying one. `dispatch_execution` is the live example: it names a
procedure and the procedure names the beamline, so the place is not
knowable until a read has happened, and today the read comes after the
authorization. Those are listed below rather than silently excluded,
because an exclusion nobody can see is how the next reader concludes
the rule is complete.
"""

import ast

import pytest

from tests.architecture.conftest import SRC_ROOT, tracked_python_files

pytestmark = pytest.mark.architecture

RESOLVED_BY_READING = frozenset(
    {
        "dispatch_execution",
        "claim_execution",
        "end_execution",
        "report_step",
        "report_step_run",
        "register_dataset",
        "register_dataset_address",
        "withdraw_dataset_address",
        "open_pursuit_round",
        "close_pursuit_round",
        "make_proposal",
        "take_proposal",
        "make_inquiry",
        "claim_inquiry",
        "answer_inquiry",
    }
)
"""Slices whose beamline is a sibling aggregate's fact, not their own.

Each would have to load something before it could name a place, and
every one of them authorizes before that read. Scoping them is a
decision about that ordering rather than about this rule, so they are
named here until it is made.
"""


def _carries_a_beamline(command: ast.Module) -> bool:
    """Whether a command dataclass declares a beamline field."""
    return any(
        isinstance(node, ast.AnnAssign)
        and isinstance(node.target, ast.Name)
        and node.target.id == "beamline"
        for klass in ast.walk(command)
        if isinstance(klass, ast.ClassDef)
        for node in klass.body
    )


def _passes_a_beamline(handler: ast.Module) -> bool:
    """Whether the handler hands a beamline to the AUTHORIZATION port.

    Narrowed to the `authorize` call on purpose. Matching any call with
    a `beamline` keyword passes against a handler that dropped it from
    the authorization and still mentions one while composing the work,
    which several of these do. That version of this function was
    written first and went green with the wiring removed.
    """
    return any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "authorize"
        and any(keyword.arg == "beamline" for keyword in node.keywords)
        for node in ast.walk(handler)
    )


def _slices_carrying_a_beamline() -> dict[str, bool]:
    """Each slice that carries a beamline, and whether it passes one."""
    found: dict[str, bool] = {}
    for path in sorted(tracked_python_files()):
        if path.name != "command.py" or "features" not in path.parts:
            continue
        if not _carries_a_beamline(ast.parse(path.read_text(encoding="utf-8"))):
            continue
        handler = path.with_name("handler.py")
        if not handler.exists():
            continue
        found[path.parent.name] = _passes_a_beamline(ast.parse(handler.read_text(encoding="utf-8")))
    return found


def test_a_command_carrying_a_beamline_is_authorized_against_it() -> None:
    carrying = _slices_carrying_a_beamline()

    assert carrying, "no slice carries a beamline, so this rule is checking nothing"
    missing = sorted(name for name, passes in carrying.items() if not passes)
    assert not missing, (
        f"these slices carry a beamline and do not pass it to authorize: {missing}. "
        "Asking without it is asking against the permissions for nowhere, which "
        "refuses the caller rather than admitting one, so nothing fails loudly."
    )


def test_every_deferred_slice_still_exists() -> None:
    """A name here that no longer names a slice hides a scoping decision.

    The list is the record of what is deliberately unscoped. A slice
    renamed out from under it quietly shrinks the list instead of
    forcing the question, which is the shape the sibling rules keep
    finding.
    """
    live = {path.parent.name for path in tracked_python_files() if path.name == "handler.py"}
    stale = sorted(RESOLVED_BY_READING - live)

    assert not stale, f"these are listed as deferred and are not slices: {stale}"


def test_the_authorization_port_offers_a_beamline() -> None:
    """The rule above is vacuous if the port never took one."""
    port = (SRC_ROOT / "keeper" / "infrastructure" / "ports" / "authorize.py").read_text(
        encoding="utf-8"
    )

    assert "beamline: str | None" in port
