"""What the installer deploys with has to be an environment that refuses defaults.

`PRODUCTION_TIER_ENVS` decides whether `build_kernel` enforces its
refusals: a real authorize adapter, authenticated callers, a policy id,
and a database role that cannot rewrite events. An environment outside
that set skips all four.

`infra/deploy/install.sh` chooses the environment every deployment runs
under. The two were agreed by hand and drifted: the installer deployed
`pilot`, the set never named it, and the only installation holding real
data ran for months with every refusal switched off. Nothing compared
them, because nothing had been asked to.

This is that comparison. It derives the environment from the installer
rather than restating it, so the failure it catches is the real one:
somebody changing what a deployment runs as, and the gates quietly
ceasing to apply to it.
"""

import re
from pathlib import Path

import pytest

from keeper.infrastructure.settings import PRODUCTION_TIER_ENVS

pytestmark = pytest.mark.architecture

_INSTALLER = Path(__file__).resolve().parents[2] / "infra" / "deploy" / "install.sh"

_APP_ENV_DEFAULT = re.compile(r'^APP_ENV="\$\{APP_ENV:-([A-Za-z0-9_-]+)\}"', re.M)


def _deployed_env() -> str:
    """The environment the installer falls back to, read from the installer.

    The default and not an override, because the override is what a
    person types once and the default is what every deployment gets.
    """
    found = _APP_ENV_DEFAULT.search(_INSTALLER.read_text())
    assert found is not None, (
        "could not find the APP_ENV default in install.sh. The line it looks "
        'for is APP_ENV="${APP_ENV:-<name>}", and if that spelling changed '
        "this check stopped comparing anything rather than started failing."
    )
    return found.group(1)


def test_the_installer_deploys_an_environment_that_refuses_permissive_defaults() -> None:
    deployed = _deployed_env()
    assert deployed.lower() in PRODUCTION_TIER_ENVS, (
        f"install.sh deploys APP_ENV={deployed}, which is not in "
        f"PRODUCTION_TIER_ENVS {sorted(PRODUCTION_TIER_ENVS)}. Every refusal in "
        "build_kernel is skipped for that environment: AllowAllAuthorize would "
        "be accepted, an unset policy id would be accepted, and a database role "
        "that can rewrite events would be accepted. Either add it to the set or "
        "deploy an environment already in it."
    )


def test_the_set_still_holds_the_names_a_deployment_might_use() -> None:
    """A guard on the check above, which passes on any single agreeing pair.

    Emptying the set and pointing the installer at nothing would satisfy
    membership vacuously, and narrowing it to only what this installer
    says would drop the names a hand-run deployment uses.
    """
    assert {"prod", "production", "staging"} <= PRODUCTION_TIER_ENVS
