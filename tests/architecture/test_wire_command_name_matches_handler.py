"""The wiring's command label must equal the handler's own constant.

Each slice handler declares a module-level `_COMMAND_NAME`. That string
is the stable label for the command: it is written into event metadata
and projection rows, and observability dashboards group on it.

The bounded context's wire module passes the same label again, as a
keyword argument to the tracing and idempotency wrappers, so that span
names and idempotency cache keys agree with the persisted row.

Two decoupled string literals naming the same thing is a silent-drift
shape. Rename one and nothing complains: the type checker sees two
unrelated strings, and every test still passes while the dashboard
quietly splits one command into two. This check ties them together.

Scope: only slices that declare the constant. Queries and factory-built
update handlers do not declare one, and are out of scope here.
"""

import ast
import importlib
import inspect
from pathlib import Path

import pytest

from tests.architecture.conftest import KEEPER_ROOT, discovered_bcs, tracked_python_files

pytestmark = pytest.mark.architecture


def _handler_command_name(handler_py: Path) -> str | None:
    """Return the handler module's command-label constant, if it declares one."""
    tree = ast.parse(handler_py.read_text())
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for tgt in node.targets:
            if (
                isinstance(tgt, ast.Name)
                and tgt.id == "_COMMAND_NAME"
                and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)
            ):
                return node.value.value
    return None


def _bind_slice_names(node: ast.AST) -> list[str]:
    """Slice names of every bind call inside this node.

    Matches the bare-name form only. The wire factory imports each slice
    as a module alias and calls bind on it, so the receiver is always a
    plain name rather than a dotted chain.
    """
    out: list[str] = []
    for n in ast.walk(node):
        if (
            isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute)
            and n.func.attr == "bind"
            and isinstance(n.func.value, ast.Name)
        ):
            out.append(n.func.value.id)
    return out


def _wire_command_name_for_slice(wire_src: str, slice_name: str) -> str | None:
    """Find the command label paired with one slice's bind call.

    A call counts as scoped to this slice when it contains that slice's
    bind and no other slice's. That filters out the outer handler-bundle
    call, which contains every slice's bind and every slice's label, while
    still admitting both layers of the tracing-wraps-idempotency sandwich.

    Both layers must carry the same literal. When they disagree this
    returns None and the caller reports it as a label that could not be
    located, which is the right outcome: there is no single answer.
    """
    tree = ast.parse(wire_src)
    matches: list[str] = []
    for call in ast.walk(tree):
        if not isinstance(call, ast.Call):
            continue
        binds = _bind_slice_names(call)
        if slice_name not in binds:
            continue
        if any(b != slice_name for b in binds):
            continue
        for inner in ast.walk(call):
            if (
                isinstance(inner, ast.keyword)
                and inner.arg == "command_name"
                and isinstance(inner.value, ast.Constant)
                and isinstance(inner.value.value, str)
            ):
                matches.append(inner.value.value)
    if not matches:
        return None
    unique = set(matches)
    return matches[0] if len(unique) == 1 else None


def _slices_with_command_name_constant() -> list[tuple[str, str, str]]:
    """Every slice whose handler declares the label, as (bc, slice, label)."""
    out: list[tuple[str, str, str]] = []
    tracked = tracked_python_files()
    for bc in discovered_bcs():
        features = KEEPER_ROOT / bc / "features"
        for handler_py in sorted(
            f
            for f in tracked
            if f.stem == "handler"
            and f.parent.parent == features
            and not f.parent.name.startswith("_")
        ):
            cmd = _handler_command_name(handler_py)
            if cmd is not None:
                out.append((bc, handler_py.parent.name, cmd))
    return out


def test_the_wire_scan_finds_at_least_one_labelled_slice() -> None:
    """Guard the enumeration: an empty parameter set skips, it does not fail."""
    assert _slices_with_command_name_constant(), (
        "No slice handler declares a command-label constant, so the agreement "
        "rule below ran against nothing."
    )


@pytest.mark.parametrize(
    ("bc", "slice_name", "handler_command_name"),
    _slices_with_command_name_constant(),
    ids=lambda v: v if isinstance(v, str) else None,
)
def test_the_wired_command_label_equals_the_handlers_own_constant(
    bc: str, slice_name: str, handler_command_name: str
) -> None:
    wire_module = importlib.import_module(f"keeper.{bc}.wire")
    wire_fn = getattr(wire_module, f"wire_{bc}", None)
    assert wire_fn is not None, f"keeper.{bc}.wire has no wire_{bc} factory"

    wire_src = inspect.getsource(wire_fn)
    wire_cmd = _wire_command_name_for_slice(wire_src, slice_name)

    assert wire_cmd is not None, (
        f"wire_{bc}: found no single command_name paired with {slice_name}'s bind "
        f"call. The handler declares {handler_command_name!r}; the wire factory "
        "must pass the same literal to both wrappers, and the two layers must "
        "agree with each other."
    )
    assert wire_cmd == handler_command_name, (
        f"wire_{bc}: the wired label {wire_cmd!r} for {slice_name} disagrees with "
        f"the handler's constant {handler_command_name!r}. The handler's constant "
        "is the source of truth, because it labels the persisted row. Change the "
        "wire literal, or change both together if the row label is meant to move."
    )
