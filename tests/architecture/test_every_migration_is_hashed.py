"""Every migration this tree ships is named in `atlas.sum`.

The suite applies migrations by executing the `.sql` files directly,
which `tests/conftest.py` explains and which is the right trade for a
test database. It means atlas never runs here, so `atlas.sum` is
invisible to every other check in this project.

Atlas does read it, at the one moment that matters. A migration added
without re-hashing the directory makes `atlas migrate apply` refuse the
whole directory with a checksum error, so the deployment stops before
any migration is applied, on a host, with nothing having changed.

## The failure that prompted it

A migration was written by hand, the suite went green across every
tier including a real Postgres, and the deployment stopped here:

```
    You have a checksum error in your migration directory.
        L25: 20260930160000_execution_tracks_what_each_step_produced.sql was added
```

The fix was one command, `make migrate-hash`, and the cost was a
failed deployment against a live keeper that had already restarted its
database container on the way to that line.

## What this checks and what it does not

The names, not the hashes. Recomputing an atlas checksum here would
mean reimplementing a format this project does not own, and getting it
subtly wrong would produce a check that fails on correct input.

What is worth catching is narrower and is the whole of what went
wrong: a file present and unlisted, or listed and absent. Atlas still
verifies the contents at apply time, which is the half that needs its
own hash function.
"""

import pytest

from tests.architecture.conftest import KEEPER_ROOT

pytestmark = pytest.mark.architecture

MIGRATIONS = KEEPER_ROOT.parents[1] / "infra" / "atlas" / "migrations"
"""`KEEPER_ROOT` is `src/keeper`, so the project root is two up."""

SUM = MIGRATIONS / "atlas.sum"


def _on_disk() -> set[str]:
    return {path.name for path in MIGRATIONS.glob("*.sql")}


def _listed() -> set[str]:
    """The migrations `atlas.sum` names, ignoring its own total.

    The first line is a hash of the whole directory and carries no
    filename, so it is dropped by taking only lines whose first field
    ends in `.sql`.
    """
    named: set[str] = set()
    for line in SUM.read_text(encoding="utf-8").splitlines():
        first = line.split(maxsplit=1)[0] if line.strip() else ""
        if first.endswith(".sql"):
            named.add(first)
    return named


def test_the_migration_directory_holds_something_to_check() -> None:
    """Guard both sides: either empty makes the comparison meaningless."""
    assert _on_disk(), f"no migrations under {MIGRATIONS}, so the rule below compares nothing"
    assert _listed(), f"{SUM} names no migration, so the rule below compares nothing"


def test_every_migration_on_disk_is_named_in_the_checksum_file() -> None:
    unhashed = sorted(_on_disk() - _listed())
    assert not unhashed, (
        f"{unhashed} are not in atlas.sum, so `atlas migrate apply` will refuse the "
        "whole directory and the deployment will stop before applying anything. "
        "Run: make migrate-hash"
    )


def test_the_checksum_file_names_no_migration_that_was_removed() -> None:
    """The other direction, which fails the same way and reads differently.

    A deleted migration leaves its line behind, and atlas refuses the
    directory for that too. It is the rarer half because migrations are
    append-only here, which is exactly why nobody would look for it.
    """
    missing = sorted(_listed() - _on_disk())
    assert not missing, (
        f"atlas.sum names {missing}, which is not in the migration directory. "
        "Run: make migrate-hash"
    )
