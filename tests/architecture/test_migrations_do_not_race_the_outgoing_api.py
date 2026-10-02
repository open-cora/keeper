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

## Why the unit is derived rather than written down

The name was spelled here once and that made this test a second place to
remember when the units were renamed, which is the kind of copy this tree
keeps finding rotted. It is now read off the template the installer
renders, so the test asks about the unit that actually gets written. That
also makes it stricter: a stop naming a unit this deployment does not
install no longer satisfies it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.architecture

DEPLOY = Path(__file__).resolve().parents[2] / "infra" / "deploy"
INSTALLER = DEPLOY / "install.sh"

_MIGRATE = "atlas migrate apply"


def _api_unit() -> str:
    """The unit the installer renders for the API, by its template.

    The API's template is the one whose name is the unit's, where the
    other two carry a suffix naming what they run. Matching on that rather
    than on a spelling keeps this test pointed at whatever the deployment
    currently installs.
    """
    templates = sorted(path.name.removesuffix(".in") for path in DEPLOY.glob("*.service.in"))
    assert templates, (
        f"{DEPLOY} renders no service templates, so this test cannot tell which "
        "unit the API runs under and is guarding nothing."
    )
    return min(templates, key=len)


def test_the_installer_stops_the_api_before_it_applies_migrations() -> None:
    script = INSTALLER.read_text(encoding="utf-8")
    stop = f"systemctl --user stop {_api_unit()}"

    assert stop in script, (
        f"{INSTALLER.name} never stops the API. A migration that resets a "
        "projection bookmark is then rebuilt by the revision being replaced."
    )
    assert _MIGRATE in script, (
        f"{INSTALLER.name} no longer applies migrations, so this test is "
        "guarding an ordering that does not exist. Delete it or fix the name."
    )
    assert script.index(stop) < script.index(_MIGRATE), (
        "the API is stopped after migrations are applied, so the outgoing "
        "revision is still subscribed when a bookmark reset lands and will "
        "rebuild the read model with the arms being replaced"
    )
