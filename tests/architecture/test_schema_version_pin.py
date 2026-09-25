"""`EXPECTED_SCHEMA_VERSION` must name the newest tracked migration.

The constant is hand-maintained on purpose: the runtime image does not ship
the migrations directory, so there is nothing on disk for the process to read
at boot. This test is what keeps the hand-maintained value honest, moving the
cost of forgetting onto CI rather than onto a deployment that refuses to start.
"""

import pytest

from keeper.infrastructure.schema import (
    EXPECTED_SCHEMA_VERSION,
    is_well_formed,
    parse_versions,
)
from tests.architecture.conftest import tracked_migration_files

pytestmark = pytest.mark.architecture


def test_expected_schema_version_matches_the_newest_migration() -> None:
    migrations = tracked_migration_files()
    assert migrations, "No tracked migrations found; the pin has nothing to check against."

    versions = parse_versions(migrations)
    newest = max(versions)
    assert newest == EXPECTED_SCHEMA_VERSION, (
        f"EXPECTED_SCHEMA_VERSION is {EXPECTED_SCHEMA_VERSION!r} but the newest "
        f"tracked migration is {newest!r}. Update the constant in "
        "aroc/infrastructure/schema.py in the same commit as the migration."
    )


def test_every_migration_filename_parses_as_a_version() -> None:
    """A filename Atlas cannot order is a migration that applies at the wrong time.

    The check has to be `is_well_formed`, not a count. `parse_versions` splits
    on the first underscore and returns whatever precedes it, so it yields one
    string per file whatever the filenames look like: comparing the two lengths
    is an identity, and the earlier version of this test asserted it.
    """
    migrations = tracked_migration_files()
    assert migrations, "No tracked migrations found; the check below examines nothing."

    malformed = [v for v in parse_versions(migrations) if not is_well_formed(v)]
    assert not malformed, (
        f"Migration filenames do not start with a YYYYMMDDHHMMSS version: {malformed}. "
        "Atlas orders by that prefix and `compare_versions` orders by string "
        "compare, so a version of a different width sorts wrong in both places."
    )
