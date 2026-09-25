"""Deciders share one signature shape, so a reader learns it once.

Per the decider section of docs/reference/patterns.md:

    create-style:  decide(state, command, *, now, new_id) -> list[Event]
    update-style:  decide(state, command, *, now)         -> list[Event]

The first two parameters are positional and are exactly state and
command, in that order. Cross-aggregate context, the clock, the id
generator and any slice-specific extra all sit after the keyword-only
marker, where they are named at every call site.

Two properties are pinned here:

  1. a top-level decide function exists in the module
  2. its positional parameters are exactly state and command

Return type is deliberately not pinned. A slice that writes several
streams at once returns a frozen wrapper holding one event list per
stream rather than a bare list, and the handler hands those lists to the
event store as a single atomic batch. That shape is documented at the
slice that needs it.

There is no allowlist. A decider whose signature diverges is conformed,
because the shape is the only reason a reader can open any decider in
this repository and already know what the first two parameters are.
"""

import ast
from pathlib import Path

import pytest

from tests.architecture.conftest import KEEPER_ROOT, discovered_bcs, tracked_python_files

pytestmark = pytest.mark.architecture


def _decider_files() -> list[Path]:
    tracked = tracked_python_files()
    out: list[Path] = []
    for bc in discovered_bcs():
        features = KEEPER_ROOT / bc / "features"
        out.extend(
            sorted(
                f
                for f in tracked
                if f.stem == "decider"
                and f.parent.parent == features
                and not f.parent.name.startswith("_")
            )
        )
    return out


def _qualified(p: Path) -> str:
    return "keeper." + ".".join(p.relative_to(KEEPER_ROOT).with_suffix("").parts)


def _find_decide_function(tree: ast.Module) -> ast.FunctionDef | None:
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "decide":
            return node
    return None


def _positional_arg_names(func: ast.FunctionDef) -> list[str]:
    return [a.arg for a in func.args.posonlyargs] + [a.arg for a in func.args.args]


def test_the_decider_signature_scan_finds_at_least_one_decider() -> None:
    """Guard the enumeration: an empty parameter set skips, it does not fail."""
    assert _decider_files(), (
        "No decider module found under any bounded context's features/ "
        "directory, so the signature rule below ran against nothing."
    )


@pytest.mark.parametrize("decider", _decider_files(), ids=_qualified)
def test_a_decider_takes_state_and_command_positionally_and_the_rest_by_keyword(
    decider: Path,
) -> None:
    qualified = _qualified(decider)
    tree = ast.parse(decider.read_text())
    func = _find_decide_function(tree)
    assert func is not None, (
        f"{qualified}: no top-level decide function. Every command and update slice exposes one."
    )

    positional = _positional_arg_names(func)
    assert positional == ["state", "command"], (
        f"{qualified}: decide takes {positional!r} positionally, expected exactly "
        "['state', 'command']. Move the extras after the keyword-only marker, per "
        "docs/reference/patterns.md."
    )
