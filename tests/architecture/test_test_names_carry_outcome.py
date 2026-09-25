"""Test function names state the property, not just the subject.

`test_<subject>_<scenario>_<expectation>`. Long is fine. A name that stops at
the subject (`test_handler`, `test_register_thing`) tells a reader which code
ran but not what was supposed to be true of it, so a failure report names a
function rather than a broken promise.

The heuristic is deliberately loose: a minimum word count plus a ban on the
vaguest endings. It catches `test_handler_works`, not every weak name. A
tighter rule would reject legitimate names and get suppressed.
"""

import ast

import pytest

from tests.architecture.conftest import tracked_test_files

pytestmark = pytest.mark.architecture

MIN_WORDS = 4
"""`test_` plus at least three more words. `test_decide_emits_x` clears it."""

VAGUE_ENDINGS = frozenset({"works", "ok", "correct", "good", "valid", "test", "it"})

NEGATORS = frozenset({"not", "never"})
"""Words that make a vague ending precise.

`test_decide_rejects_a_schema_that_is_not_valid` is a good name: "valid" is
the predicate being negated, not a hand-wave. Without this carve-out the rule
rejected it, which is the kind of false positive that gets a rule suppressed
rather than obeyed.
"""


def _is_fixture(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """True when the function carries a pytest fixture decorator."""
    for decorator in node.decorator_list:
        target = decorator.func if isinstance(decorator, ast.Call) else decorator
        if isinstance(target, ast.Attribute) and target.attr == "fixture":
            return True
        if isinstance(target, ast.Name) and target.id == "fixture":
            return True
    return False


def test_every_test_function_name_states_an_outcome() -> None:
    offenders: list[str] = []
    for path in sorted(tracked_test_files()):
        try:
            tree = ast.parse(path.read_text())
        except SyntaxError:  # pragma: no cover
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            if not node.name.startswith("test_"):
                continue
            if _is_fixture(node):
                # A fixture is not a test, even when it is `test_`-prefixed.
                # The prefix is a mistake worth fixing at the fixture, but it
                # must not be reported here as a weak TEST name.
                continue
            words = node.name.split("_")
            if len(words) < MIN_WORDS:
                offenders.append(f"{path.name}:{node.lineno}: {node.name} (too few words)")
            elif words[-1] in VAGUE_ENDINGS and words[-2] not in NEGATORS:
                offenders.append(f"{path.name}:{node.lineno}: {node.name} (vague ending)")
    assert not offenders, "Test names that name a subject but not an outcome:\n" + "\n".join(
        offenders
    )
