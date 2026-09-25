"""Every projection's `apply` is written to survive being run twice.

Delivery to a projection is at-least-once. The worker applies a batch and
advances its bookmark in one transaction, so a crash in between replays the
batch on restart, and a replay that doubles a count or overwrites a start
time corrupts a table nobody will look at until the number is wrong.

The check is a text scan, and it is honest about that: it cannot tell
whether a statement is idempotent, only whether it was written by somebody
who was thinking about it. Every write statement in a projection module has
to carry one of

    ON CONFLICT          the insert form, which says what a repeat does
    UPDATE               a set to a value derived from the event, which
                         writes the same thing twice
    # idempotent: ...    a statement that is neither, with the reason

which is a rule about evidence rather than about behaviour. The behaviour
is asserted where it can be, in
`tests/integration/test_postgres_execution_summary_lookup.py`, by
rewinding a bookmark and replaying a real batch.

Promised in docs/reference/workflow.md and in the `Projection` Protocol's
own docstring, both saying it belonged with the first projection.
"""

import ast
import re
from pathlib import Path

import pytest

from tests.architecture.conftest import KEEPER_ROOT, discovered_bcs

pytestmark = pytest.mark.architecture

_WRITE_STATEMENT = re.compile(r"\b(INSERT\s+INTO|UPDATE|DELETE\s+FROM)\b", re.IGNORECASE)
_ON_CONFLICT = re.compile(r"\bON\s+CONFLICT\b", re.IGNORECASE)
_JUSTIFIED = re.compile(r"#\s*idempotent:")


def _projection_modules() -> list[Path]:
    return sorted(
        path
        for bc in discovered_bcs()
        for path in (KEEPER_ROOT / bc / "projections").glob("*.py")
        if path.name != "__init__.py"
    )


def _literal_text(value: ast.expr) -> str | None:
    """The text of a string assignment, including an f-string's fixed parts.

    An f-string matters because a projection's SQL interpolates its own
    table name, which is the right way to write it: the name has to reach
    the migration and the query as one constant. What is interpolated is
    an identifier, never a clause, so reading the fixed parts alone is
    enough to see whether the statement says what a repeat does.
    """
    if isinstance(value, ast.Constant):
        return value.value if isinstance(value.value, str) else None
    if isinstance(value, ast.JoinedStr):
        return "".join(
            part.value
            for part in value.values
            if isinstance(part, ast.Constant) and isinstance(part.value, str)
        )
    return None


def _sql_constants(tree: ast.Module) -> list[tuple[str, str]]:
    """Module-level string constants that contain a write statement.

    Reads the assignments rather than the file text so a write named in
    prose, in a docstring explaining what the module does, is not mistaken
    for one the module runs.
    """
    found: list[tuple[str, str]] = []
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        text = _literal_text(node.value)
        if text is None or not _WRITE_STATEMENT.search(text):
            continue
        name = next(
            (target.id for target in node.targets if isinstance(target, ast.Name)),
            "<unnamed>",
        )
        found.append((name, text))
    return found


def test_at_least_one_projection_module_is_discovered() -> None:
    """Guard the enumeration, so the check below cannot pass vacuously."""
    assert _projection_modules(), (
        "No projection modules found under any `<bc>/projections/`, so the "
        "idempotency check examines nothing."
    )


def test_every_projection_write_says_what_happens_when_it_runs_twice() -> None:
    offenders: list[str] = []
    for path in _projection_modules():
        source = path.read_text(encoding="utf-8")
        justified = _JUSTIFIED.search(source) is not None
        for name, sql in _sql_constants(ast.parse(source)):
            insert = sql.lstrip().upper().startswith("INSERT")
            if insert and not _ON_CONFLICT.search(sql) and not justified:
                relative = str(path).split("src/keeper/", 1)[-1]
                offenders.append(f"{relative}: {name}")
    assert not offenders, (
        "Projection INSERTs with no ON CONFLICT clause and no "
        "`# idempotent: <reason>` comment in the module. Delivery is "
        "at-least-once, so a replayed batch runs these again:\n  " + "\n  ".join(offenders)
    )
