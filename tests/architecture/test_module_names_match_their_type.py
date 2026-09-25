"""A module that defines a type is named after it.

`ports/` and `adapters/` were the only two directories in this package whose
filenames matched their contents perfectly, and they were the only two with a
fitness test saying so. Everywhere else drifted: a module named for a
configuration that defined a settings class, a module named for a handler
that defined no handler, a module whose filename abbreviated a class name
its siblings spelled out. The correlation between "enforced" and
"consistent" is the argument for this file. Renaming without a check just
restarts the clock.

## What counts as a match

A module matches when any public class it defines snake-cases to:

  - the filename                      `kernel.py`     -> `Kernel`
  - the folder plus the filename      `projection/worker.py` -> `ProjectionWorker`
  - the filename as a prefix or       `projection/wakeup.py` -> `WakeupSource`
    suffix of the class

The folder-prefix form is the one worth naming. A directory already supplies
a category, so repeating it in the filename says it twice. Letting the
folder carry the prefix is what allowed the modules under `slices/` to drop
the qualifiers they were carrying at the package root.

## The inverted regime inside a bounded context

An aggregate folder and a slice folder read the other way round: the FOLDER
names the subject and the FILE names the role it plays.

    folder                    module    defines
    ------------------------  --------  --------------------
    <bc>                      wire      <Bc>Handlers
    aggregates/thing          state     Thing
    aggregates/thing          events    ThingRegistered
    features/register_thing   command   RegisterThing
    features/register_thing   route     RegisterThingRequest

Under the rule above, every one of those reads as a violation, because none
of them is named after its file. So a class matching the FOLDER counts too,
and only for a module whose parent directory is `aggregates` or `features`.
Allowing it everywhere would let any module pass by naming a class after the
directory it happens to sit in, which is most of what this check is for.

This rule was written while the package had no bounded contexts, from a
corpus that contained only one of the two regimes. The carve-out is what the
first bounded context cost it.

## What the rule does not apply to

A module with no public class is a function namespace: `logging.py`,
`pool.py`. There is no type to be named after, and demanding one
would invent a class per module. Error and response classes do not count as
the subject either, so a module exporting three functions and one error
class is still a namespace.

That leaves a small set of modules that DO export subject types and are
still namespaces, because the types are a function's parameters or its
result rather than the point of the module. Those are declared below, and
declaring one costs a line of reasoning.
"""

import ast
from pathlib import Path

import pytest

from tests.architecture.conftest import discovered_bcs, tracked_python_files

pytestmark = pytest.mark.architecture

NAMESPACE_MODULES: frozenset[str] = frozenset(
    {
        # Exports `build_kernel` plus `AuthorizeFactory`, the Protocol describing
        # one of its arguments. The module is the composition root, not a module
        # about factories.
        "infrastructure/deps.py",
    }
)
"""Modules that export a public type and are still function namespaces.

Separate from the automatic exemption for modules with no public class at
all. An entry here is a claim that the types present are a function's
parameters or its result, not the module's subject.
"""

_NOT_A_SUBJECT = ("Error", "Response")
"""Class-name suffixes that never make a module class-shaped.

Nearly every namespace module raises something. A module exporting four
functions and one error class is not a module about that error.
"""


def _snake(name: str) -> str:
    out: list[str] = []
    for i, char in enumerate(name):
        boundary = (
            char.isupper()
            and i > 0
            and not (name[i - 1].isupper() and (i + 1 >= len(name) or name[i + 1].isupper()))
        )
        if boundary:
            out.append("_")
        out.append(char.lower())
    return "".join(out)


def _subject_classes(tree: ast.Module) -> list[str]:
    return [
        node.name
        for node in tree.body
        if isinstance(node, ast.ClassDef)
        if not node.name.startswith("_")
        if not node.name.endswith(_NOT_A_SUBJECT)
    ]


_SUBJECT_FOLDER_PARENTS = frozenset({"aggregates", "features"})
"""Directory names whose children name a SUBJECT rather than a category.

Inside one of these, the folder is the aggregate or the slice and the file
is the role it plays. That inverts the usual reading, so the inversion is
scoped rather than allowed everywhere.
"""


def _folder_names_the_subject(path: Path) -> bool:
    """True when the folder holding this module names a domain subject.

    Three kinds of folder do: a bounded context, an aggregate, and a slice.
    In all three the directory is the thing and the file is the role it
    plays in it, which is the reverse of how the chassis reads.

    The bounded-context case is the one that is easy to miss. A wiring
    module holds `<Bc>Handlers`, a bundle named for the context rather than
    for the file, and there is nothing else it could sensibly be called.
    """
    return (
        path.parent.parent.name in _SUBJECT_FOLDER_PARENTS or path.parent.name in discovered_bcs()
    )


def _matches(class_name: str, path: Path) -> bool:
    snake = _snake(class_name)
    stem, folder = path.stem, path.parent.name
    if (
        snake == stem
        or snake == f"{folder}_{stem}"
        or snake.endswith(f"_{stem}")
        or snake.startswith(f"{stem}_")
    ):
        return True
    # The inverted regime: inside an aggregate or slice folder the subject is
    # the folder, so a class named after it matches whatever the file is
    # called. Scoped, because allowing it everywhere would let any module in
    # a directory pass by naming a class after the directory.
    if not _folder_names_the_subject(path):
        return False
    return snake == folder or snake.startswith(f"{folder}_") or _qualifies(snake, folder)


def _qualifies(snake: str, folder: str) -> bool:
    """The folder's words appear in the class, in order, with more between.

    A slice acting on a per-aggregate sub-concept names the sub-concept
    in the folder and the aggregate in the class: the directory
    `grant_permission` holds `GrantPolicyPermission`. Both spellings are
    required by docs/reference/conventions.md, which explains why they
    differ: a directory is read with the aggregate around it, and a
    command class name escapes into an event envelope, a span, an
    idempotency key, and a permission inside a policy, where nothing
    around the string says what it acts on.

    A subsequence rather than a substring, because the inserted word
    goes in the middle. Order is required, so `permission_grant` does
    not pass for a folder called `grant_permission`, which is the R3
    direction mistake this repository records as the one most often made
    backwards.
    """
    wanted = folder.split("_")
    remaining = iter(snake.split("_"))
    return all(word in remaining for word in wanted)


def test_every_module_defining_a_type_is_named_after_one_of_them() -> None:
    offenders: list[str] = []
    for path in sorted(tracked_python_files()):
        if path.name == "__init__.py":
            continue
        relative = str(path).split("src/keeper/", 1)[-1]
        if relative in NAMESPACE_MODULES:
            continue
        classes = _subject_classes(ast.parse(path.read_text()))
        if not classes:
            continue
        if not any(_matches(name, path) for name in classes):
            offenders.append(f"{relative}: defines {', '.join(classes)}")
    assert not offenders, (
        "Modules whose filename names none of the types they define, and which "
        "do not sit in an aggregate or slice folder naming the subject. Rename "
        "the file to its subject, let the folder carry the category, or add it "
        "to NAMESPACE_MODULES with the reason its types are not its subject:\n  "
        + "\n  ".join(offenders)
    )


def test_every_declared_namespace_module_still_exists_and_still_needs_the_entry() -> None:
    """A stale exemption is worse than none: it reads as a considered decision
    while covering a file that has moved or has since been renamed correctly."""
    tracked = {str(p).split("src/keeper/", 1)[-1] for p in tracked_python_files()}
    missing = sorted(NAMESPACE_MODULES - tracked)
    assert not missing, f"NAMESPACE_MODULES names files that no longer exist: {missing}"

    unnecessary: list[str] = []
    for relative in sorted(NAMESPACE_MODULES):
        path = next(p for p in tracked_python_files() if str(p).endswith(relative))
        classes = _subject_classes(ast.parse(path.read_text()))
        if not classes or any(_matches(name, path) for name in classes):
            unnecessary.append(relative)
    assert not unnecessary, (
        f"NAMESPACE_MODULES entries that would now pass on their own; drop them: {unnecessary}"
    )
