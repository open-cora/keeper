"""The append-only guarantee is a database grant, not a convention.

`events` must be INSERT-only for the application role. The convention is
easy to state and impossible to enforce in application code, because the
thing it protects against is application code. So it is enforced by the role
the application connects as, and asserted here at the SQL-text level so a
future migration cannot quietly widen it.

This is a text check, and it is NOT the weaker half of a pair. It and the
integration test at `tests/integration/test_events_append_only_postgres.py`
catch different things, which mutation testing showed rather than reasoning:

  - Delete the REVOKE, and ONLY this test fails. The integration test still
    passes, because the role was never GRANTed those privileges to begin with,
    so effective access does not change. The REVOKE is defence against a
    future blanket grant, and its absence is invisible at runtime until that
    grant arrives.
  - Add a GRANT of UPDATE, and BOTH fail: this one on the text, the
    integration one on the refusal that stops happening.

So neither subsumes the other, and the obvious intuition (the one that runs
against a real database must be strictly stronger) is wrong here.
"""

import re

import pytest

from tests.architecture.conftest import append_only_table_lineage, tracked_migration_files

pytestmark = pytest.mark.architecture

APP_ROLE = "keeper_app"


_LINE_COMMENT = re.compile(r"--[^\n]*")


def _migration_text() -> str:
    """Concatenated migration SQL with `--` comments stripped.

    Stripping matters: these migrations DISCUSS grants and revokes in prose,
    so a naive scan matches the word GRANT inside a comment explaining why a
    REVOKE is there and reports the opposite of the truth. The first version
    of this check did exactly that.
    """
    return "\n".join(_LINE_COMMENT.sub("", path.read_text()) for path in tracked_migration_files())


def test_events_is_discovered_as_an_append_only_table() -> None:
    """Guard the discovery itself, so the checks below cannot pass vacuously."""
    lineage = append_only_table_lineage()
    assert "events" in lineage, (
        "`events` was not discovered in the migration lineage, so every "
        "append-only check below would pass by examining nothing."
    )


def test_append_only_tables_revoke_mutation_from_the_app_role() -> None:
    text = _migration_text()
    for table in sorted(append_only_table_lineage()):
        pattern = re.compile(
            rf"REVOKE\s+[^;]*\bON\s+{re.escape(table)}\b[^;]*FROM\s+{APP_ROLE}",
            re.IGNORECASE | re.DOTALL,
        )
        assert pattern.search(text), (
            f"No REVOKE of UPDATE / DELETE / TRUNCATE on `{table}` from "
            f"`{APP_ROLE}` in any migration. An append-only table whose role "
            "can still mutate it is append-only by convention only."
        )


def test_append_only_tables_are_never_granted_mutation() -> None:
    """A later GRANT would silently undo the REVOKE above."""
    text = _migration_text()
    for table in sorted(append_only_table_lineage()):
        pattern = re.compile(
            rf"\bGRANT\b[^;]*?\b(UPDATE|DELETE|TRUNCATE)\b[^;]*?\bON\s+{re.escape(table)}\b",
            re.IGNORECASE,
        )
        match = pattern.search(text)
        assert match is None, (
            f"A migration GRANTs mutation on the append-only table `{table}`: "
            f"{match.group(0)[:120]!r}"
        )
