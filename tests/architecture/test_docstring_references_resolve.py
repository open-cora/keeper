"""A docstring may not name code or files that do not exist.

This repository was copied from a sibling codebase and stripped to its
chassis. The code that survived the strip compiles and is type-checked; its
prose was not checked by anything, so docstrings kept describing classes,
functions, migrations and design documents that came across only as names.
A reader cannot tell the difference between a name they have not found yet
and a name that is not there, so every such reference costs a search that
ends in nothing.

Three rules, all decidable:

  - A backticked CamelCase name in a docstring must be defined somewhere in
    `src/` or `tests/`, or be declared in `EXTERNAL_NAMES` below.
  - So must a backticked SCREAMING_SNAKE constant or a backticked
    leading-underscore private name. Both were outside the first version
    of this check, which keyed on CamelCase alone. The omission cost the
    review that found it: one docstring named two constants and a private
    helper that this repository has never defined, and read as green
    through the whole infrastructure sweep.
  - So must the HEAD of a dotted or called span. A class this repository
    has never had sat in a shipping adapter, hidden by the `.all()` after
    it, next door to a private name hidden by the capital letter after its
    underscore. Each pattern was anchored to the whole span, so a span that
    was a little more than a bare name matched nothing at all.
  - A file path cited in a docstring must exist in the repository.

Neither rule can see a wrong explanation of a real symbol. They catch the
cheaper failure: prose that refers to nothing at all.
"""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false

import ast
import builtins
import itertools
import re
from pathlib import Path

import pytest

from tests.architecture.conftest import (
    REPO_ROOT,
    tracked_file_basenames,
    tracked_migration_files,
    tracked_python_files,
    tracked_test_files,
)

pytestmark = pytest.mark.architecture

EXTERNAL_NAMES: frozenset[str] = frozenset(
    {
        # Postgres
        "AccessExclusiveLock",
        # asyncpg
        "PoolConnectionProxy",
        "Record",
        # starlette / fastapi / mcp
        "ServerErrorMiddleware",
        "Context",
        # typing / stdlib
        "Coroutine",
        "CoroutineType",
        "TypeAlias",
        # HTTP header names and auth schemes
        "Host",
        "Authorization",
        "Bearer",
        # typing
        "Optional",
        # PyJWT
        "PyJWT",
        # Spring Security 6, named in a corpus comparison
        "AuthorizationManager",
        # OpenTelemetry environment variables, read by the SDK itself
        "OTEL_EXPORTER_OTLP_ENDPOINT",
        "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT",
        # OpenTelemetry Span methods and the instrumentor's guard attribute
        "record_exception",
        "set_status",
        "is_instrumented_by_opentelemetry",
        # Postgres functions, named in the advance query's cursor pattern
        "pg_current_snapshot",
        "pg_snapshot_xmin",
        # PyJWT keyword on `jwt.decode`
        "decode_complete",
        # OAuth 2.0 grant type, and the RFC 9728 metadata field
        "client_credentials",
        "authorization_servers_metadata",
        # nginx directive, cited by the body-size limit it has to agree with
        "client_max_body_size",
        # Cedar, named in the same corpus comparison as AuthorizationManager
        "is_authorized",
    }
)
"""CamelCase names that are real but defined outside this repository.

Declared rather than pattern-matched: an unknown name is a defect by
default, and admitting one should cost a line of evidence. Python builtins
are admitted separately since `dir(builtins)` already enumerates them.
"""

PROSPECTIVE_NAMES: frozenset[str] = frozenset(
    {
        # Shapes the first bounded context should take. Named here before
        # anything defines them, which is the point: the docstring is telling
        # a future author what to call the thing, not citing one that exists.
        "Handler",
        "Item",
        "Page",
        "SurfaceKind",
        # Worked examples inside `bounded_text`'s own docstrings, standing in
        # for the per-aggregate value object a BC declares for itself. Plan now
        # declares a real one, `PlanName`; these three stay undefined because
        # the examples name aggregates that hold no text.
        "MethodName",
        "PolicyName",
        "InvalidPolicyNameError",
        # Alternatives considered and rejected. The prose exists to say why
        # they are absent, so requiring them to be present inverts it.
        # `ActorRegister` is a malformed event name the naming rules cite
        # as an example of what they refuse: its verb is not in the past.
        "ActorRegister",
        "BoundedText",
        "Builder",
        "Llm",
        "TestDatabase",
        "Test",
        # The per-value-object length bound each aggregate declares in its
        # own state module. Plan declares `PLAN_NAME_MAX_LENGTH`; the bare
        # `MAX_LENGTH` is the placeholder the convention is written with, and
        # is deliberately a constant nowhere.
        "MAX_LENGTH",
        # A stand-in enum in a worked example about exception wrapping.
        "SomeEnum",
        # A word, not a symbol: the naming style itself, and a filename in a
        # worked example about trailing whitespace.
        "snake_case",
        "scan_005",
        # Worked-example names inside the rules that judge names. Each is an
        # input the rule accepts or refuses, so defining them would be
        # defining the thing the example exists to describe. `permission_grant`
        # and the bare `test_handler` shapes are the refused ones.
        "permission_grant",
        "stream_type_name",
        "test_decide_emits_x",
        "test_decide_rejects_a_schema_that_is_not_valid",
        "test_handler",
        "test_handler_works",
        "test_register_thing",
        # A test name that was replaced, cited by its replacement to say what
        # the gap was. Requiring it to exist would undo the rename.
        "test_the_created_actor_is_not_readable_yet",
    }
)
"""Names this repository deliberately does not define.

Distinct from `EXTERNAL_NAMES`, which are real elsewhere. These are real
nowhere: a shape a future slice should adopt, a stand-in inside a worked
example, or an alternative the prose rejects by name. Each still costs a
line here, so an entry is a decision rather than a way past the check.
"""

_SPAN = re.compile(r"`([^`\n]+)`")
"""Anything between backticks, on one line.

The span is not the name. Prose writes `Kernel.authz`, `SomeEnum(payload[k])`
and `Optional[X] = None`, and the name a reader would go looking for is the
head of each: the part before the first dot, bracket or parenthesis. Matching
the whole span instead is what let a dotted reference to a class this
repository does not have sit in a shipping adapter."""

_NAME_SHAPES = (
    re.compile(r"^[A-Z][a-zA-Z0-9]*[a-z][a-zA-Z0-9]*$"),
    re.compile(r"^_?[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+$"),
    re.compile(r"^_[A-Za-z][A-Za-z0-9_]*$"),
    re.compile(r"^_?[a-z][a-z0-9]*(?:_[a-z0-9]+)+$"),
)
"""The four shapes a head has to have before it is worth resolving:
CamelCase, a SCREAMING_SNAKE constant, a leading-underscore private name, and
a snake_case name.

Everything else between backticks is left alone, because prose backticks
plain words, SQL, HTTP verbs and header values too. The constant shape needs
at least one underscore for the same reason: `CHECK`, `NULL` and `POST` are
not constants this repository declares, and every constant it does declare
carries one. The snake_case shape needs one for the same reason again, and it
is the shape that matters most here: a function, a slice folder and a log
prefix all wear it, and the names this repository inherited and never defined
were almost all of that shape. Leaving it out is what let four docstrings
promise an operator slice that does not exist."""


def _cited_names(doc: str) -> list[str]:
    """Heads of every backticked span whose shape says it names code."""
    heads: list[str] = []
    for span in _SPAN.findall(doc):
        span = span.strip()
        # A span with a space inside it is a phrase, not a reference:
        # `Malformed {vo_type} payload`, `BCs -> infrastructure -> shared`,
        # `Phase 8e`. Only a single token can be looked up.
        if not span or " " in span:
            continue
        head = re.split(r"[.(\[]", span, maxsplit=1)[0]
        if head and any(shape.match(head) for shape in _NAME_SHAPES):
            heads.append(head)
    return heads


_FILE_PATH = re.compile(r"`?\b([A-Za-z0-9_./-]+\.(?:py|sql|md|toml|yml|yaml|hcl|cff))\b`?")
_MIGRATION = re.compile(r"\b(20\d{12}_[a-z0-9_]+)")
"""An Atlas migration cited without its `.sql` suffix.

A separate pattern because the path regex keys on the extension, and the
timestamped name reads as a version rather than a file. One such reference
survived the first sweep for exactly that reason."""


def _all_python_files() -> list[Path]:
    return sorted(tracked_python_files() | tracked_test_files())


_SQL_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def _defined_names() -> frozenset[str]:
    """Every name this repository binds anywhere: classes, functions, module
    stems, folder names, assignments, parameters, keyword arguments,
    attributes, imported symbols, and the identifiers the migrations declare.

    Deliberately over-inclusive. The rule is about prose that refers to
    nothing, so the cost of admitting a name that exists in some other sense
    is far lower than the cost of a false failure on a real one.

    Three of those sources were added with the snake_case shape, because
    without them that shape would have failed on names that are real:

      - Folder names, because a slice IS its folder. Nothing binds
        `deactivate_actor`, and prose naming the slice is naming something
        the tree has.
      - Keyword arguments, because a log line's fields are written as
        keywords at the call site and read as names in the prose describing
        the line.
      - Migration identifiers, because a table or a column is declared in
        SQL and cited in Python. Reading them out of the migrations resolves
        them the honest way, rather than by listing each as an exception.
    """
    names = set(dir(builtins)) | EXTERNAL_NAMES | PROSPECTIVE_NAMES
    for migration in tracked_migration_files():
        names.update(_SQL_IDENTIFIER.findall(migration.read_text()))
    for path in _all_python_files():
        names.add(path.stem)
        names.update(path.relative_to(REPO_ROOT).parts[:-1])
        for node in ast.walk(ast.parse(path.read_text())):
            match node:
                case ast.ClassDef() | ast.FunctionDef() | ast.AsyncFunctionDef():
                    names.add(node.name)
                case ast.Name(ctx=ast.Store()):
                    names.add(node.id)
                case ast.arg():
                    names.add(node.arg)
                case ast.keyword(arg=str() as keyword_name):
                    names.add(keyword_name)
                case ast.Attribute():
                    names.add(node.attr)
                case ast.Constant(value=str() as text):
                    # A string literal in the same file makes the name real:
                    # event-type discriminants, `Literal[...]` arms and dict
                    # keys are code, even though they are not definitions.
                    names.add(text)
                case ast.TypeVar():
                    names.add(node.name)
                case ast.Import() | ast.ImportFrom():
                    names.update((a.asname or a.name).split(".")[-1] for a in node.names)
                case _:
                    pass
    return frozenset(names)


def _docstrings(path: Path) -> list[str]:
    """Every docstring in the file, including attribute docstrings.

    `ast.get_docstring` covers modules, classes and functions. It does not
    cover the bare string after an assignment (PEP 258), which this codebase
    uses for constants: `NOTIFY_CHANNEL`, `NIL_SENTINEL_ID`, the readiness
    budgets. Those are 31 docstrings that went unchecked until a mutation
    planted in one of them survived.
    """
    tree = ast.parse(path.read_text())
    docs = [
        doc
        for node in ast.walk(tree)
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef)
        if (doc := ast.get_docstring(node))
    ]
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if not isinstance(body, list):
            continue
        for assignment, following in itertools.pairwise(body):
            if not isinstance(assignment, ast.Assign | ast.AnnAssign):
                continue
            match following:
                case ast.Expr(value=ast.Constant(value=str() as text)):
                    docs.append(text)
                case _:
                    pass
    return docs


def test_docstring_class_names_resolve_to_a_definition_in_the_tree() -> None:
    defined = _defined_names()
    unresolved: list[str] = []
    for path in _all_python_files():
        for doc in _docstrings(path):
            for name in _cited_names(doc):
                if name not in defined:
                    unresolved.append(f"{path.relative_to(REPO_ROOT)}: `{name}`")
    assert not unresolved, (
        "Docstrings name symbols that are defined nowhere in src/ or "
        "tests/. Either the symbol was left behind when this repo was stripped "
        "(rewrite the prose), or it is real and external (add it to "
        "EXTERNAL_NAMES with a comment saying where it lives):\n  "
        + "\n  ".join(sorted(unresolved))
    )


def test_docstring_file_citations_resolve_to_a_path_in_the_repo() -> None:
    tracked = tracked_file_basenames()
    unresolved: list[str] = []
    for path in _all_python_files():
        for doc in _docstrings(path):
            for line in doc.splitlines():
                # A URL is a citation of someone else's tree, not of ours.
                if "http" in line or re.search(r"\b[a-z0-9-]+\.(?:com|org|io|net)/", line):
                    continue
                for cited in _FILE_PATH.findall(line) + [
                    f"{stem}.sql" for stem in _MIGRATION.findall(line)
                ]:
                    basename = cited.split(":")[0].split("/")[-1]
                    if basename not in tracked:
                        unresolved.append(f"{path.relative_to(REPO_ROOT)}: {cited}")
    assert not unresolved, (
        "Docstrings cite files that do not exist in this repository. A reader "
        "cannot follow them, so the claim they support cannot be checked:\n  "
        + "\n  ".join(sorted(unresolved))
    )
