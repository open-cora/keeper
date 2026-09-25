"""Every member of an aggregate's event union has a deserializer arm.

Its sibling check pins that each arm that EXISTS wraps its payload errors.
Neither that one nor the type checker notices an arm that is missing
altogether: a new event class added to the union and forgotten in the
match statement falls through to the wildcard, and surfaces either as a
generic unknown-event-type failure at replay or, worse, as a row silently
dropped by a comprehension that swallows the error.

The check runs in both directions:

  1. find the union alias whose name ends in Event
  2. find the deserializer
  3. for each case arm, work out which class its body constructs
  4. assert every union member is constructed by some arm, AND every arm
     constructs a class that is in the union

The second direction matters as much as the first. An arm building a
class that left the union is dead dispatch, and reads as working code.

An arm whose case string does not match the class it builds is accepted.
That is the shape a renamed event type takes: the old string stays
dispatchable so historical rows still load, while the class it builds
carries the new name.
"""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING

import pytest

from tests.architecture.conftest import KEEPER_ROOT, tracked_python_files

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.architecture


def _event_files() -> list[Path]:
    return sorted(
        f
        for f in tracked_python_files()
        if f.stem == "events"
        and f.parent.parent.name == "aggregates"
        and f.parent.parent.parent.parent == KEEPER_ROOT
    )


def _qualified(p: Path) -> str:
    return "keeper." + ".".join(p.relative_to(KEEPER_ROOT).with_suffix("").parts)


def _collect_names_in_union(node: ast.expr) -> list[str]:
    """Flatten a pipe-separated union expression into its member names."""
    out: list[str] = []
    if isinstance(node, ast.Name):
        out.append(node.id)
    elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        out.extend(_collect_names_in_union(node.left))
        out.extend(_collect_names_in_union(node.right))
    elif (
        isinstance(node, ast.Subscript)
        and isinstance(node.value, ast.Name)
        and node.value.id == "Union"
    ):
        # The subscript spelling, for a module that reaches for it.
        slice_node = node.slice
        elements = slice_node.elts if isinstance(slice_node, ast.Tuple) else [slice_node]
        for elt in elements:
            out.extend(_collect_names_in_union(elt))
    return out


def _find_event_union(tree: ast.Module) -> tuple[str, list[str]] | None:
    """Find the top-level union alias whose target name ends in Event."""
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name) or not target.id.endswith("Event"):
            continue
        names = _collect_names_in_union(node.value)
        if len(names) >= 2:
            return target.id, names
    return None


def _find_from_stored(tree: ast.Module) -> ast.FunctionDef | None:
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "from_stored":
            return node
    return None


def _builder_target_class(call: ast.Call, case_scope: ast.AST) -> str | None:
    """Resolve the event class built by a shared-helper call.

    Two spellings are recognised: a lambda that constructs the class
    directly, and a named nested builder function whose return statement
    constructs it.
    """
    if not (isinstance(call.func, ast.Name) and call.func.id == "deserialize_or_raise"):
        return None
    if len(call.args) < 2:
        return None
    builder = call.args[1]
    if isinstance(builder, ast.Lambda) and isinstance(builder.body, ast.Call):
        body_call = builder.body
        if isinstance(body_call.func, ast.Name):
            return body_call.func.id
        return None
    if isinstance(builder, ast.Name):
        for node in ast.walk(case_scope):
            if isinstance(node, ast.FunctionDef) and node.name == builder.id:
                for sub in ast.walk(node):
                    if (
                        isinstance(sub, ast.Return)
                        and isinstance(sub.value, ast.Call)
                        and isinstance(sub.value.func, ast.Name)
                    ):
                        return sub.value.func.id
        return None
    return None


def _string_literals_in_pattern(pattern: ast.pattern) -> list[str]:
    """Every string literal a case pattern dispatches on.

    Handles the single-literal arm and the or-pattern arm that keeps an
    old event-type string dispatchable alongside its replacement. Capture,
    class and mapping patterns return nothing: they do not dispatch on the
    discriminator string and are out of scope.
    """
    if (
        isinstance(pattern, ast.MatchValue)
        and isinstance(pattern.value, ast.Constant)
        and isinstance(pattern.value.value, str)
    ):
        return [pattern.value.value]
    if isinstance(pattern, ast.MatchOr):
        out: list[str] = []
        for sub in pattern.patterns:
            out.extend(_string_literals_in_pattern(sub))
        return out
    return []


def _collect_case_targets(func: ast.FunctionDef) -> dict[str, str | None]:
    """Map each dispatchable string to the class its arm constructs."""
    out: dict[str, str | None] = {}
    for node in ast.walk(func):
        if not isinstance(node, ast.Match):
            continue
        for case in node.cases:
            case_strings = _string_literals_in_pattern(case.pattern)
            if not case_strings:
                continue
            target: str | None = None
            for body_node in ast.walk(case):
                if not (
                    isinstance(body_node, ast.Return) and isinstance(body_node.value, ast.Call)
                ):
                    continue
                call = body_node.value
                if isinstance(call.func, ast.Name) and call.func.id == "deserialize_or_raise":
                    target = _builder_target_class(call, case)
                    break
                if isinstance(call.func, ast.Name):
                    target = call.func.id
                    break
            for case_str in case_strings:
                out[case_str] = target
    return out


def test_the_union_coverage_scan_finds_at_least_one_aggregate() -> None:
    """Guard the enumeration: an empty parameter set skips, it does not fail.

    Separate from the rule below skipping a single-event aggregate, which
    is a decision made per aggregate FOUND. This fails when none was.
    """
    assert _event_files(), (
        "No events module found inside any aggregate folder, so the union "
        "coverage rule below ran against nothing."
    )


@pytest.mark.parametrize("events_file", _event_files(), ids=_qualified)
def test_every_union_member_is_reachable_through_the_deserializer(
    events_file: Path,
) -> None:
    qualified_module = _qualified(events_file)
    tree = ast.parse(events_file.read_text())

    union = _find_event_union(tree)
    if union is None:
        pytest.skip(f"{qualified_module}: no event union (a single-event aggregate)")
    union_name, union_members = union
    union_set = set(union_members)

    from_stored = _find_from_stored(tree)
    assert from_stored is not None, (
        f"{qualified_module}: declares {union_name} but no deserializer, so no "
        "stored row of any of its types can be read back."
    )

    case_targets = _collect_case_targets(from_stored)
    constructed = {target for target in case_targets.values() if target is not None}

    missing = union_set - constructed
    assert not missing, (
        f"{qualified_module}: the deserializer has no arm constructing "
        f"{sorted(missing)}, which {union_name} declares. A stored row of that "
        "type cannot be read back."
    )

    foreign = {
        case_str: target
        for case_str, target in case_targets.items()
        if target is not None and target not in union_set
    }
    assert not foreign, (
        f"{qualified_module}: the deserializer builds classes that {union_name} "
        f"does not declare: {foreign}. Either the union lost a member or the "
        "dispatch is dead."
    )
