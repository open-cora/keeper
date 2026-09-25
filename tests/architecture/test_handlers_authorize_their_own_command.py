"""Every handler gates on the command name it declares.

A slice names its command once, as `_COMMAND_NAME`, and that string is
used in three places: the authorization call, the event envelope, and its
log lines. Only the first of them decides anything.

Slices are written by copying the nearest one, which is how a new handler
ends up authorizing under its neighbour's name. Nothing about that is
visible. The slice works, its tests pass, its events carry the right
label, and the gate it runs is the wrong gate: a principal permitted to
grant could revoke, or a read could be admitted by a permission somebody
was given for something else.

`AllowAllAuthorize` is what makes this silent. It answers the same way
whatever it is handed, and it is the adapter every test below the
contract tier runs against, so no behavioural test in this repository can
see the argument at all.

## What is checked

The rule used to be "find the `.authorize(...)` call in this handler and
require its `command_name` to be the bare name `_COMMAND_NAME`". It was
rewritten when Execution hoisted its five run-transition handlers into a
shared shell, which put the gate somewhere the old rule could not see.

That hoist was then reverted, on the grounds that duplication between
slices is the price of vertical slicing rather than a defect, and that
handlers were not even the most duplicated file in those slices. The
rewritten rule stayed, because it is the better rule either way: it was
never really about shells.

So the rule follows the name instead of the call, in two halves.

First: EVERY `command_name=` a slice passes must be the bare
`_COMMAND_NAME`. A handler passes it up to four times, to the gate, to
the event envelope and to two log lines, and the old rule looked at one
of them. This is the stronger reading of "a slice names its command
once", and it was available all along.

Second: exactly one of those calls must be a gate, meaning either
`.authorize(...)` itself or a hoisted shell that gates on what it is
given. The shells are checked separately, at the bottom of this file.

A literal string is refused in either position even when it is the right
string, because the whole point of the constant is that the next edit to
it reaches every use.

## The shell checks currently range over nothing, and that is correct

There are no shells in the tree today, so the parametrized shell test at
the bottom collects an empty set and reports as a skip. That is the shape
`test_fitness_scope.py` exists to be suspicious of, so it is worth saying
why this instance is not the failure mode that file warns about.

Nothing here is passing because it examined zero subjects. Every slice is
still checked, by the two halves above, and the first half refuses
delegation to anything this file cannot follow: a handler handing its
command name to an unrecognised callee fails with the list of shells it
could have used. So a shell cannot appear without its check appearing
with it. The moment a module matching the shell shape lands at a
bounded-context root, the scan collects it and the dormant test wakes up
ranging over it.

That self-arming property is why these two tests stay after the revert
rather than being deleted as speculative. Without them the delegation
branch above would be an open door.

Read from the source rather than by importing, for the same reason as the
rest of this directory: a fact that holds because an import happened to
succeed is weaker than one written down.
"""

import ast
from pathlib import Path

import pytest

from tests.architecture.conftest import KEEPER_ROOT, discovered_bcs, tracked_python_files

pytestmark = pytest.mark.architecture


def _handler_modules() -> list[Path]:
    """Every slice handler under a bounded context's features/ directory."""
    return sorted(
        path
        for path in tracked_python_files()
        if path.name == "handler.py"
        and path.parent.parent.name == "features"
        and path.parent.parent.parent.name in discovered_bcs()
    )


def _shell_modules() -> list[Path]:
    """Hoisted handler shells at a bounded-context root.

    docs/reference/layout.md calls for one of these once three update
    slices on an aggregate share the same scaffolding, and names it after
    the aggregate it serves. The match here is deliberately broader than
    that name: any private module at a bounded-context root whose stem
    ends in handler. A shell hoisting something other than an update is
    then still checked rather than quietly unguarded.
    """
    return sorted(
        path
        for path in tracked_python_files()
        if path.parent.name in discovered_bcs()
        and path.name.startswith("_")
        and path.stem.endswith("_handler")
    )


def _slice_id(path: Path) -> str:
    rel = path.relative_to(KEEPER_ROOT)
    return f"{rel.parts[0]}/{path.parent.name}"


def _shell_id(path: Path) -> str:
    return str(path.relative_to(KEEPER_ROOT))


def _functions_defined(tree: ast.Module) -> set[str]:
    return {
        node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def _calls_passing_command_name(tree: ast.Module) -> list[ast.Call]:
    """Every call in the module that passes a `command_name=` keyword."""
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        if any(kw.arg == "command_name" for kw in node.keywords)
    ]


def _authorize_calls(tree: ast.Module) -> list[ast.Call]:
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "authorize"
    ]


def _is_authorize(call: ast.Call) -> bool:
    return isinstance(call.func, ast.Attribute) and call.func.attr == "authorize"


def _callee_name(call: ast.Call) -> str | None:
    if isinstance(call.func, ast.Name):
        return call.func.id
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    return None


def _shells_by_function() -> dict[str, Path]:
    """Which shell module defines each hoisted bind function."""
    out: dict[str, Path] = {}
    for shell in _shell_modules():
        tree = ast.parse(shell.read_text(encoding="utf-8"))
        for name in _functions_defined(tree):
            if not name.startswith("_"):
                out[name] = shell
    return out


def test_the_handler_scan_finds_a_handler_in_every_bounded_context() -> None:
    """Guard the enumeration: an empty parameter set skips, it does not fail."""
    found = _handler_modules()
    contexts = {p.relative_to(KEEPER_ROOT).parts[0] for p in found}
    assert contexts == set(discovered_bcs()), (
        f"handlers found in {sorted(contexts)}, bounded contexts are "
        f"{sorted(discovered_bcs())}. The rule below would range over only part "
        "of the tree."
    )


@pytest.mark.parametrize("handler", _handler_modules(), ids=_slice_id)
def test_a_handler_gates_on_the_command_name_it_declares(handler: Path) -> None:
    tree = ast.parse(handler.read_text(encoding="utf-8"))
    calls = _calls_passing_command_name(tree)
    assert calls, (
        f"{_slice_id(handler)} never passes command_name= to anything. Every "
        "command and every query passes a gate, and a handler that names no "
        "command is a handler running somebody else's."
    )

    wrong = [
        ast.unparse(kw.value)
        for call in calls
        for kw in call.keywords
        if kw.arg == "command_name"
        if not (isinstance(kw.value, ast.Name) and kw.value.id == "_COMMAND_NAME")
    ]
    assert not wrong, (
        f"{_slice_id(handler)} passes {wrong} rather than _COMMAND_NAME. A "
        "slice names its command once, so the gate it runs, the label on its "
        "events and its log lines cannot disagree. A literal is refused even "
        "when it is the right literal, because the next edit to the constant "
        "will not reach it."
    )

    shells = _shells_by_function()
    gates = [c for c in calls if _is_authorize(c) or _callee_name(c) in shells]
    assert len(gates) == 1, (
        f"{_slice_id(handler)} hands its command name to {len(gates)} gates. "
        "Exactly one call must either authorize or delegate to a hoisted shell "
        f"that does. Known shells define {sorted(shells)}. Zero means nothing "
        "verifiable gates this slice; two is a reader asking which one decides."
    )


def test_the_shell_scan_and_the_delegating_slices_agree() -> None:
    """Every shell exists because some slice delegates to it.

    A shell nothing calls would pass its own rule below while guarding
    nothing, and a slice delegating to a module this scan does not collect
    is caught above. This is the pair in the middle: it fails if the two
    enumerations drift apart.
    """
    shells = _shells_by_function()
    delegated: set[str] = set()
    for handler in _handler_modules():
        tree = ast.parse(handler.read_text(encoding="utf-8"))
        for call in _calls_passing_command_name(tree):
            if not _is_authorize(call):
                name = _callee_name(call)
                if name is not None:
                    delegated.add(name)

    unused = set(shells) - delegated
    assert not unused, (
        f"hoisted shell functions nothing delegates to: {sorted(unused)}. A "
        "shell exists to be shared; one with no callers is dead scaffolding "
        "that still passes every check below."
    )


@pytest.mark.parametrize("shell", _shell_modules(), ids=_shell_id)
def test_a_hoisted_shell_gates_on_the_name_it_was_given(shell: Path) -> None:
    """The other half: the shell must use the name, not one of its own.

    A shell taking `command_name` and then authorizing under a literal
    would satisfy every slice-side check in this file while running one
    gate for five different commands.
    """
    tree = ast.parse(shell.read_text(encoding="utf-8"))
    calls = _authorize_calls(tree)
    assert len(calls) == 1, (
        f"{_shell_id(shell)} makes {len(calls)} authorize calls. A shell that "
        "gates more than once is asking a reader which one decides, and one "
        "that never gates is a shell every delegating slice is trusting to."
    )

    passed = [kw.value for kw in calls[0].keywords if kw.arg == "command_name"]
    assert len(passed) == 1, (
        f"{_shell_id(shell)} does not pass command_name= to authorize. Pass it "
        "by keyword: the port takes principal, command and surface, and two of "
        "the three are easy to swap positionally."
    )

    gate = passed[0]
    assert isinstance(gate, ast.Name) and gate.id == "command_name", (
        f"{_shell_id(shell)} authorizes under {ast.unparse(gate)} rather than "
        "its own command_name parameter. The whole reason a slice may hand its "
        "name across is that the shell gates on what it was handed; a literal "
        "here runs one gate for every slice that delegates."
    )
