"""Adapter classes are `<Tech><Port>`, with no `Adapter` suffix.

`PostgresEventStore`, `JwtTokenVerifier`, `InMemoryIdempotencyStore`. The port
name is the tail, so an adapter sorts next to its siblings and reads as "the
Postgres one of these" rather than as a separate noun.

The suffix is banned because it carries no information: every class in these
directories is an adapter, so saying so distinguishes nothing while making
every name four characters longer.

## Where adapters live

Two homes, and the rule is the same in both. `infrastructure/adapters/` holds
the ones every bounded context could use; `<bc>/adapters/` holds one a single
context supplies because it is the context that owns what the port means.
`PolicyAuthorize` is the first of the second kind: the `Authorize` port is
declared in infrastructure because everything calls it, and implemented in
Authority because a policy is Authority's to interpret.

This file scoped to the infrastructure directory alone until that adapter
arrived, which would have left the convention unenforced in exactly the place
a new one was most likely to be written from memory.

## Read from git, not from the filesystem

`tracked_python_files()` rather than `glob`. An untracked adapter is invisible
to pre-commit, so a rule that saw it here would report a problem the commit
could not contain, and, worse, a rule that PASSED on an untracked tree reads
as evidence about files git has never seen.
"""

import ast
from pathlib import Path

import pytest

from tests.architecture.conftest import KEEPER_ROOT, tracked_python_files

pytestmark = pytest.mark.architecture

ALLOWED_NON_ADAPTER_SUFFIXES = ("Registry", "Error")
"""Classes in an adapters package that are not themselves adapters.

A version-dispatch registry holds adapters rather than being one, and an error
class raised by an adapter belongs beside it. Both are named for what they
are; neither should be forced into the `<Tech><Port>` shape.
"""


def _adapter_modules() -> list[Path]:
    """Every tracked module in any `adapters/` package under `keeper`."""
    return sorted(
        path
        for path in tracked_python_files()
        if path.parent.name == "adapters" and path.name != "__init__.py"
    )


def _label(path: Path) -> str:
    return str(path.relative_to(KEEPER_ROOT))


def _public_classes(path: Path) -> list[str]:
    return [
        node.name
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, ast.ClassDef) and not node.name.startswith("_")
    ]


def test_the_scan_finds_adapters_in_every_package_that_holds_them() -> None:
    """Guard the enumeration, so the checks below cannot pass vacuously.

    Two assertions, because the first would still hold if the scan had
    silently narrowed back to one directory, which is the regression this
    file was just widened out of.
    """
    modules = _adapter_modules()
    assert modules, "No adapter modules found; the checks below examine nothing."

    packages = {path.parent.relative_to(KEEPER_ROOT) for path in modules}
    assert len(packages) >= 2, (
        f"Adapters found in only {sorted(str(p) for p in packages)}. A bounded "
        "context supplies one too, so a scan seeing a single package has "
        "stopped ranging over the tree."
    )


@pytest.mark.parametrize("module", _adapter_modules(), ids=_label)
def test_no_adapter_class_carries_an_adapter_suffix(module: Path) -> None:
    offenders = [name for name in _public_classes(module) if name.endswith("Adapter")]
    assert not offenders, (
        f"{_label(module)} declares {offenders}, carrying a redundant `Adapter` "
        "suffix. Name them `<Tech><Port>`."
    )


@pytest.mark.parametrize("module", _adapter_modules(), ids=_label)
def test_an_adapter_module_filename_is_snake_case_of_its_class(module: Path) -> None:
    """A filename that does not match its class is a grep that fails."""
    classes = [
        name for name in _public_classes(module) if not name.endswith(ALLOWED_NON_ADAPTER_SUFFIXES)
    ]
    if not classes:
        pytest.skip(f"{_label(module)} declares no adapter class")

    stem = module.stem.replace("_", "")
    assert any(cls.lower() == stem for cls in classes), (
        f"{_label(module)} declares {classes}, none of which snake-cases to its filename."
    )
