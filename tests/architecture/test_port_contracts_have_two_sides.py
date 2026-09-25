"""A shared port contract is run against more than one adapter.

The suites under `tests/_port_contracts/` exist to say that two
implementations of a port behave alike. Run against one adapter, such a
suite still passes, still looks thorough, and compares nothing. Deleting
the second driver is a one-line change that costs the contract its whole
reason for existing and breaks no test, which is the shape of a check
that quietly stops checking.

So the rule is derived rather than pinned: a contract module and the
files that import it are written in different places by different acts,
and the count of the second is the evidence. Nothing is listed by hand
here, so a new contract is covered the moment it exists.

Two rather than some larger number because two is where comparison
starts. A port with three adapters and only two drivers is a judgment
call about whether the third is a real alternative or a decorator, and a
rule cannot make that call. A port with one driver is not a judgment
call.
"""

import ast
from functools import cache

import pytest

from tests.architecture.conftest import tracked_test_files

pytestmark = pytest.mark.architecture

_PACKAGE = "tests._port_contracts"


@cache
def _contract_modules() -> tuple[str, ...]:
    """Every shared contract suite, by module name."""
    return tuple(
        sorted(
            path.stem
            for path in tracked_test_files()
            if path.parent.name == "_port_contracts" and not path.stem.startswith("__")
        )
    )


@cache
def _drivers_by_contract() -> dict[str, frozenset[str]]:
    """Test files importing each contract, keyed by contract module name.

    Read from imports rather than from filenames, because a driver is
    defined by running the suite, not by being called one.
    """
    found: dict[str, set[str]] = {name: set() for name in _contract_modules()}
    for path in tracked_test_files():
        if path.parent.name == "_port_contracts":
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.ImportFrom) or not node.module:
                continue
            if not node.module.startswith(f"{_PACKAGE}."):
                continue
            imported = node.module.removeprefix(f"{_PACKAGE}.")
            if imported in found:
                found[imported].add(path.name)
    return {name: frozenset(drivers) for name, drivers in found.items()}


def test_the_port_contract_scan_finds_at_least_one_contract() -> None:
    """Guard the enumeration: an empty parameter set skips, it does not fail."""
    assert _contract_modules(), (
        f"No contract suite found under {_PACKAGE}, so the rule below ran against nothing."
    )


@pytest.mark.parametrize("contract", _contract_modules())
def test_a_port_contract_runs_against_at_least_two_adapters(contract: str) -> None:
    drivers = _drivers_by_contract()[contract]
    assert len(drivers) >= 2, (
        f"{_PACKAGE}.{contract} is imported by {sorted(drivers) or 'nothing'}.\n"
        "A shared contract with one driver compares no two implementations. "
        "It passes, reads as thorough, and is evidence about a single adapter "
        "that would be cheaper to test directly.\n"
        "Either add the driver that went missing, or delete the contract and "
        "move its checks into the one adapter's own file."
    )
