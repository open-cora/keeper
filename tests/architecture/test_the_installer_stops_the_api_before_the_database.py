"""The deploy takes the API down across every step that touches the database.

`infra/deploy/install.sh` restarts Postgres, applies migrations and
rotates the application role's password. A keeper left running across
any of that is a process holding a pool against a database being moved
underneath it, and the two failures that causes do not look alike.

The restart severs the pool mid-request, so the outgoing revision spends
it failing callers. The migration is worse and quieter: it may reset a
projection bookmark so a read model rebuilds against the new code, and a
worker from the revision being replaced will take that reset and rebuild
with its own arms, leaving the bookmark at the end of the log with
nothing left to replay and the deploy reporting success.

The installer once restarted Postgres first and stopped the API
afterwards, which left exactly that window open. This pins the order
rather than the prose, because the comment explaining it sat beside the
statement and the statement was in the wrong place.
"""

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.architecture

_INSTALLER = Path(__file__).resolve().parents[2] / "infra" / "deploy" / "install.sh"

_STEPS = {
    "stop the api": re.compile(r"^systemctl --user stop \S*keeper\.service", re.M),
    "restart postgres": re.compile(r"^systemctl --user restart \S*keeper-postgres\.service", re.M),
    "apply migrations": re.compile(r"^\(cd \"\$\{ATLAS_DIR\}\".*atlas migrate apply", re.M),
    "start the api": re.compile(r"^systemctl --user restart \S*keeper\.service", re.M),
}
"""Each step, matched on the part of the unit name this project owns.

The prefix every unit carries is the deploying tree's convention rather
than this project's, and a mirror of this repository is built to stand on
its own, so pinning it here would couple the suite to a name that belongs
outside it. The suffix is enough to tell the three units apart: only one
of them ends in `keeper-postgres.service`, and the API's own pattern does
not match it because that name has no `keeper.service` in it.
"""

_REQUIRED_ORDER = ("stop the api", "restart postgres", "apply migrations", "start the api")


def _offsets() -> dict[str, int]:
    """Where each step sits in the installer, by character offset.

    Every step must appear exactly once. More than one match would make
    an ordering claim ambiguous, and the first occurrence could be
    ordered correctly while a second was not.
    """
    text = _INSTALLER.read_text()
    found: dict[str, int] = {}
    for name, pattern in _STEPS.items():
        matches = pattern.findall(text)
        assert len(matches) == 1, (
            f"expected exactly one line in install.sh for {name!r}, found "
            f"{len(matches)}. Either the step moved and this check stopped "
            "comparing anything, or it now happens twice and the order below "
            "says less than it appears to."
        )
        match = pattern.search(text)
        assert match is not None
        found[name] = match.start()
    return found


def test_the_api_is_down_for_every_step_that_touches_the_database() -> None:
    offsets = _offsets()
    actual = sorted(_REQUIRED_ORDER, key=lambda step: offsets[step])
    assert actual == list(_REQUIRED_ORDER), (
        f"install.sh runs these as {actual}, and they have to run as "
        f"{list(_REQUIRED_ORDER)}. Anything between stopping and starting the "
        "API is a window where the keeper is up with the database moving "
        "under it."
    )
