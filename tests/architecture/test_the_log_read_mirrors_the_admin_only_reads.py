"""The streams the log withholds are the ones the deployed policy withholds.

Two lists in two trees say the same thing and neither imports the other.
`keeper.api.event_log` decides which streams a general log read returns,
and `infra/deploy/policy_matrix.py` decides which principal holds which
grant. If they drift, the log is either refusing a stream the policy
grants or returning one it does not, and no other check in this repository
compares them.

The second rule here is the one that fires on a change nobody is thinking
about. A new aggregate arrives with a new stream type, and because the
route filters on an allow list, its events are invisible until somebody
names them. That is the safe direction and a silent one, so this makes the
omission fail rather than go unnoticed.
"""

import importlib.util
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from keeper.api.event_log import ADMIN_ONLY_STREAM_TYPES, ALL_STREAM_TYPES, GENERAL_STREAM_TYPES

pytestmark = pytest.mark.architecture

_REPO_ROOT = Path(__file__).resolve().parents[2]
_POLICY_MATRIX = _REPO_ROOT / "infra" / "deploy" / "policy_matrix.py"

_STREAM_FOR_ADMIN_ONLY_READ: dict[str, str] = {
    "GetActor": "Actor",
    "GetPolicy": "Policy",
}
"""Which aggregate's stream sits behind each read the administrator keeps.

Written out rather than derived. A command name does not carry its
aggregate anywhere a test could read it, and a derivation that guessed by
string surgery would pass on a name it had mangled. Two entries, each
obvious to a reader, and a third admin-only read fails the first
assertion below until somebody adds it here and decides what the log
should do with its stream.
"""


def _policy_matrix() -> Any:
    """Load the deployment's rulebook, which is a script and not a module."""
    spec = importlib.util.spec_from_file_location("_policy_matrix_under_test", _POLICY_MATRIX)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _declared_stream_types() -> dict[str, str]:
    """Every `*_STREAM_TYPE = "..."` the tracked source declares, by file.

    Enumerated through `git ls-files`, so a file git has never seen is
    invisible here exactly as it is to every other rule in this tier.
    """
    listing = subprocess.run(
        ["git", "ls-files", "src"],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    pattern = re.compile(r'^[A-Z_]*STREAM_TYPE\s*(?::\s*[A-Za-z]+\s*)?=\s*"([A-Za-z]+)"', re.M)
    found: dict[str, str] = {}
    for line in listing.stdout.splitlines():
        if not line.endswith(".py"):
            continue
        path = _REPO_ROOT / line
        for value in pattern.findall(path.read_text()):
            found.setdefault(value, line)
    return found


def test_every_admin_only_read_has_its_stream_named_here() -> None:
    matrix = _policy_matrix()
    assert set(matrix.ADMIN_ONLY_READS) == set(_STREAM_FOR_ADMIN_ONLY_READ), (
        "The administrator's reads changed and the stream behind each is no "
        "longer written down. Add the new read to _STREAM_FOR_ADMIN_ONLY_READ "
        "with the stream its aggregate opens, then decide whether the general "
        "log read should still return it."
    )


def test_the_log_withholds_exactly_the_administrators_streams() -> None:
    expected = set(_STREAM_FOR_ADMIN_ONLY_READ.values())
    assert set(ADMIN_ONLY_STREAM_TYPES) == expected, (
        "The streams the log withholds are not the streams behind the reads "
        "the administrator keeps. Turning the log on is only safe while these "
        "agree: a stream missing here is one a viewer can read and a direct "
        "read of its aggregate would refuse."
    )


def test_the_log_knows_every_stream_type_the_tree_declares() -> None:
    declared = _declared_stream_types()
    missing = set(declared) - set(ALL_STREAM_TYPES)
    assert not missing, (
        "Stream types are declared in the tree and absent from "
        "ALL_STREAM_TYPES, so the log read filters them out and nothing says "
        "so:\n" + "\n".join(f"    {name} declared in {declared[name]}" for name in sorted(missing))
    )


def test_the_log_names_no_stream_type_the_tree_does_not_declare() -> None:
    declared = _declared_stream_types()
    invented = set(ALL_STREAM_TYPES) - set(declared)
    assert not invented, (
        "ALL_STREAM_TYPES names streams no aggregate opens, so the filter "
        "carries entries that match nothing: " + ", ".join(sorted(invented))
    )


def test_the_two_grants_differ_by_the_administrators_streams() -> None:
    assert GENERAL_STREAM_TYPES == ALL_STREAM_TYPES - ADMIN_ONLY_STREAM_TYPES


def test_the_deployed_policy_grants_both_log_reads() -> None:
    """The viewer holds the general read and the administrator holds both."""
    matrix = _policy_matrix()
    granted = {(subject, command) for subject, command, _ in matrix.grants()}
    assert (matrix.VIEWER, "ReadEventLog") in granted
    assert (matrix.ADMIN, "ReadEventLog") in granted
    assert (matrix.ADMIN, "ReadFullEventLog") in granted
    assert (matrix.VIEWER, "ReadFullEventLog") not in granted
    for beamline in matrix.BEAMLINES:
        assert (beamline, "ReadEventLog") not in granted
        assert (beamline, "ReadFullEventLog") not in granted
