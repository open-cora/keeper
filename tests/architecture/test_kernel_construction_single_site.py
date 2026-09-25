"""`Kernel(...)` is constructed in exactly two places.

`make_inmemory_kernel` and `make_postgres_kernel` are the only call sites.
Everything else, tests included, goes through one of them.

The reason is field growth. A `Kernel` built inline somewhere carries that
site's idea of the defaults, frozen at the moment it was written. Add a field
and every inline site is silently wrong in a way nothing reports: the
dataclass supplies a default, the test passes, and the deployment behaves
differently from the test. Two construction sites means one place to add the
field and one place to reason about what it defaults to.
"""

import ast
from pathlib import Path

import pytest

from tests.architecture.conftest import tracked_python_files, tracked_test_files

pytestmark = pytest.mark.architecture

ALLOWED_SITES = frozenset({"deps.py"})
"""Files permitted to call `Kernel(...)` directly.

`kernel.py` itself is absent deliberately: it DEFINES the dataclass but does
not construct it.
"""


def _kernel_construction_sites(paths: frozenset[Path]) -> list[str]:
    hits: list[str] = []
    for path in sorted(paths):
        if path.name in ALLOWED_SITES:
            continue
        try:
            tree = ast.parse(path.read_text())
        except SyntaxError:  # pragma: no cover  # a parked or partial file
            continue
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "Kernel"
            ):
                hits.append(f"{path}:{node.lineno}")
    return hits


def test_kernel_is_constructed_only_by_the_factory_functions() -> None:
    hits = _kernel_construction_sites(tracked_python_files())
    assert not hits, (
        "Direct `Kernel(...)` construction outside deps.py:\n"
        + "\n".join(hits)
        + "\nUse make_inmemory_kernel or make_postgres_kernel so a new field "
        "gets one default rather than one per site."
    )


def test_tests_build_kernels_through_the_factories_too() -> None:
    """Tests are the site that drifts first, and the one that hides the drift.

    A test that builds a `Kernel` inline keeps passing when a field is added,
    because the dataclass default fills the gap. The production path may take
    a different default from the same addition, and nothing compares them.
    """
    hits = _kernel_construction_sites(tracked_test_files())
    assert not hits, (
        "Direct `Kernel(...)` construction in tests:\n"
        + "\n".join(hits)
        + "\nUse make_inmemory_kernel so a new field cannot default differently "
        "here than it does in production."
    )
