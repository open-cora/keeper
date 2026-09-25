"""Importing the ports brings no framework, driver or SDK with it.

A port is the domain's side of a boundary. What sits behind it should be
swappable, and a deciding function should be able to name a port's types
without dragging a web server into the process.

This was not true and nothing noticed. `Authorize` took a UUID sentinel
from `keeper.infrastructure.request`, which imports FastAPI to read
headers off a live request, so importing the authorization port loaded
a web framework behind it. Every test still passed, the application
still booted, and the only symptom was that a pure decider could not
name the system principal without doing the same.

## Why a subprocess

The property is about what a fresh interpreter loads. By the time a test
runs, the suite has already imported FastAPI for its own reasons, so
checking `sys.modules` in-process would report the framework present
however clean the ports were, and would pass for the wrong reason
forever. A subprocess is the only way to ask the real question.

The list is the things whose absence is load-bearing rather than every
third-party package: a web framework, a database driver, and the two
SDKs an adapter is expected to hold and a port is not.
"""

import subprocess
import sys

import pytest

pytestmark = pytest.mark.architecture

FORBIDDEN_AT_THE_PORT: tuple[str, ...] = (
    "fastapi",
    "starlette",
    "pydantic",
    "asyncpg",
    "mcp",
    "jwt",
)
"""Packages no port may pull in, directly or through anything it imports.

`pydantic` is here with the rest because a port that reaches for it is
describing a wire shape, and a wire shape belongs to the adapter that
speaks that wire.
"""

_PROBE = """
import sys
import keeper.infrastructure.ports
print(",".join(sorted(m for m in {names} if m in sys.modules)))
"""


def test_importing_the_ports_package_loads_no_framework_or_driver() -> None:
    result = subprocess.run(
        [sys.executable, "-c", _PROBE.format(names=repr(list(FORBIDDEN_AT_THE_PORT)))],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, f"probe failed to run:\n{result.stderr}"

    loaded = [name for name in result.stdout.strip().split(",") if name]
    assert not loaded, (
        "Importing keeper.infrastructure.ports pulled in: "
        + ", ".join(loaded)
        + ".\nA port names domain types. Whatever needs one of these belongs "
        "in the adapter behind the port, not in the port itself. Check what "
        "the port imports, and what THAT module imports."
    )


def test_the_probe_can_report_a_package_that_is_loaded() -> None:
    """Guard the instrument: a probe that reports nothing proves nothing.

    The test above passes when its output is empty, which is also what a
    broken probe produces. This runs the same machinery against a module
    that certainly does load one of the forbidden names, so an empty
    answer above means absence rather than silence.
    """
    probe = _PROBE.replace(
        "import keeper.infrastructure.ports", "import keeper.infrastructure.request"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe.format(names=repr(list(FORBIDDEN_AT_THE_PORT)))],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, f"probe failed to run:\n{result.stderr}"
    assert "fastapi" in result.stdout, (
        "The probe found no framework behind a module that imports FastAPI "
        "directly, so it is not measuring what it claims to."
    )
