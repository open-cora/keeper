"""A migration must not be applied while the revision it replaces is running.

Deploying re-runs `infra/deploy/install.sh`, which applies migrations and
then restarts the API. Those two in that order are fine for a migration
that only changes a schema, and wrong for one that asks a read model to be
rebuilt.

A projection is rebuilt by resetting its bookmark, which the migration does
in SQL. Whatever is subscribed when that lands does the rebuilding, and
until the restart that is the revision being replaced. It rebuilds with its
own arms, moves the bookmark to the end of the log, and the incoming
revision finds nothing to replay.

Measured on the deployment rather than imagined: a migration adding a
column and resetting a bookmark was consumed by the previous revision,
which left the new column null on every row and the column it replaced
holding values no current arm writes. Nothing failed and the deploy
reported success, which is why a test says so rather than a comment alone.

Scoped to the stop preceding the migration, which is the ordering that
makes the race impossible. How the API is started again afterwards is the
installer's business and is checked by the installer running at all.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.architecture

INSTALLER = Path(__file__).resolve().parents[2] / "infra" / "deploy" / "install.sh"

_STOP = "systemctl --user stop keeper.service"
_MIGRATE = "atlas migrate apply"


def test_the_installer_stops_the_api_before_it_applies_migrations() -> None:
    script = INSTALLER.read_text(encoding="utf-8")

    assert _STOP in script, (
        f"{INSTALLER.name} never stops the API. A migration that resets a "
        "projection bookmark is then rebuilt by the revision being replaced."
    )
    assert _MIGRATE in script, (
        f"{INSTALLER.name} no longer applies migrations, so this test is "
        "guarding an ordering that does not exist. Delete it or fix the name."
    )
    assert script.index(_STOP) < script.index(_MIGRATE), (
        "the API is stopped after migrations are applied, so the outgoing "
        "revision is still subscribed when a bookmark reset lands and will "
        "rebuild the read model with the arms being replaced"
    )
