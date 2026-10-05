"""What the installer deploys with has to be an environment that refuses defaults.

`DEVELOPMENT_TIER_ENVS` decides whether `build_kernel` enforces its
refusals: a real authorize adapter, authenticated callers, a policy id,
and a database role that cannot rewrite events. An environment named in
that set skips all four.

`infra/deploy/install.sh` chooses the environment every deployment runs
under. The two were once agreed by hand and drifted: the list named only
production environments, the installer deployed `pilot`, and the only
installation holding real data ran for months with every refusal
switched off. Nothing compared them, because nothing had been asked to.

Two checks, against the two ways that can happen again. The first derives
the environment from the installer rather than restating it, so it
catches somebody changing what a deployment runs as. The second covers
the direction the list can be weakened from the other end, by growing
until it swallows an environment that holds a record.
"""

import re
from pathlib import Path

import pytest

from keeper.infrastructure.settings import DEVELOPMENT_TIER_ENVS, Settings

pytestmark = pytest.mark.architecture

_INSTALLER = Path(__file__).resolve().parents[2] / "infra" / "deploy" / "install.sh"

_APP_ENV_DEFAULT = re.compile(r'^APP_ENV="\$\{APP_ENV:-([A-Za-z0-9_-]+)\}"', re.M)

_NAMES_THAT_MUST_BE_GATED = (
    "prod",
    "production",
    "staging",
    "pilot",
    "beamline",
    "aps-u",
    "",
)
"""Spellings a deployment might use, including ones nothing here has met.

The last two are the point. `aps-u` and the empty string are not names
this project has agreed anywhere, and a list of production environments
could not have covered them. Gating by exclusion does, which is the
property worth pinning rather than the specific words.
"""


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
    assert Settings(app_env=deployed).is_production_tier, (
        f"install.sh deploys APP_ENV={deployed}, which is in "
        f"DEVELOPMENT_TIER_ENVS {sorted(DEVELOPMENT_TIER_ENVS)}. Every refusal "
        "in build_kernel is skipped for that environment: AllowAllAuthorize "
        "would be accepted, an unset policy id would be accepted, and a "
        "database role that can rewrite events would be accepted. Either "
        "deploy an environment outside that set or stop calling this one "
        "development."
    )


@pytest.mark.parametrize("env", _NAMES_THAT_MUST_BE_GATED)
def test_an_environment_this_list_does_not_know_is_gated_rather_than_exempt(env: str) -> None:
    """The fail-closed direction, which is the reason the list holds this side.

    A list of production names would have to have met each of these to
    gate it, and would exempt every name it had not. Growing the
    development set until it covers one of these is the edit this
    catches.
    """
    assert Settings(app_env=env).is_production_tier


def test_the_environments_the_suite_and_the_example_run_as_stay_permissive() -> None:
    """The other direction, so the check above cannot be satisfied by gating all.

    `test` is what `tests/conftest.py` sets and `local` is both the field
    default and what `.env.example` ships. Gating either would refuse to
    boot everywhere development happens, so the suite would say so
    loudly, but it would say it in every test at once rather than here.
    """
    assert not Settings(app_env="test").is_production_tier
    assert not Settings().is_production_tier
