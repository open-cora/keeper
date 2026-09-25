"""Every aggregate pins the stream type it files its rows under.

A stream type is a wire format. It goes into the `stream_type` column on
append and is used to find those rows again on load, so renaming it does
not rename the rows already written: it hides them. The value is a fact
about stored data rather than an implementation detail, and changing it
is a data migration rather than a refactor.

Nothing else in the tree can serve as the second opinion on it. The
writing handler and the reading loader both import one constant, so they
agree however it is spelled, and a round trip through a real database
agrees too, because every row it reads back was filed under whatever the
constant said at write time. Renaming the constant moves both ends at
once and no assertion can disagree. That was measured rather than
assumed: with `ACTOR_STREAM_TYPE` set to `"Aktor"`, all 230 unit tests
passed, and so did 6 of the 8 Access integration tests, the two failures
coming from a query that happened to spell `"Actor"` out by hand.

So the second opinion is written here, deliberately. `PINNED_STREAM_TYPES`
spells out the literal each aggregate must produce, the way
`EXPECTED_ACCESS_TOOLS` and `EXPECTED_OPENAPI_PATHS` spell out the
surfaces this system publishes outward. Same habit, pointed at the
surface it publishes downward.

Two rules, because they fail for different reasons:

    every aggregate declares exactly one stream-type constant
        an aggregate with none appears on neither side of the comparison
        below, so both sides agree and the subject is simply missing,
        which is what a check that looks like it ranges over everything
        does when it does not

    the declared literals equal the pinned ones
        a renamed value and an unpinned new aggregate both fail here

Editing a pinned value to make a red run green throws away the only
record of what the rows on disk are called. Change it when there is a
migration behind the change, and not otherwise.
"""

import ast
from functools import cache

import pytest

from tests.architecture.conftest import KEEPER_ROOT, discovered_aggregates, tracked_python_files

pytestmark = pytest.mark.architecture

_SUFFIX = "_STREAM_TYPE"

PINNED_STREAM_TYPES: dict[str, str] = {
    "access/actor": "Actor",
    "authority/policy": "Policy",
    "execution/plan": "Plan",
    "counsel/proposal": "Proposal",
    "custody/dataset": "Dataset",
    "equipment/device": "Device",
    "execution/execution": "Execution",
    "execution/procedure": "Procedure",
}
"""The stream type each aggregate writes, keyed as `<bc>/<aggregate>`.

One entry per aggregate, spelled out rather than imported. Importing the
constant here would reproduce the exact defect this file exists to close.
"""

RETIRED_STREAM_TYPES: dict[str, str] = {
    "execution/walk": "Walk",
    "execution/run": "Run",
}
"""Stream types this tree has written and no longer writes.

Kept rather than deleted, because deleting the line is exactly what the
docstring above warns against: the pin is the only record of what the
rows on disk are called, and a rename that erases the old value leaves
nothing saying what the orphaned rows were filed under.

Nothing asserts against this. It is a record for a person reading the
log or a future migration, not a rule, and an entry here means those
rows exist and no current code can load them.

`Walk` became `Execution` when the aggregate stopped being a record of
something a driver told this system about and became one this system
dispatches. The migration in the same change rebuilds the summary table
and says what it cannot recover.

`Run` was retired rather than renamed, and nothing took its place. A run
and one acquisition step of a procedure were the same fact in two
vocabularies, so the step is what other contexts point at now. Its rows
are still in the events table and no code in this tree can load them,
which is the state an entry here is for.
"""


def _stream_types_in_source(source: str) -> tuple[tuple[str, str | None], ...]:
    """Module-level `*_STREAM_TYPE` constants in one file, with their literals.

    A constant whose value is not a plain string literal comes back as
    `None` rather than being skipped, so it fails the pin. A computed
    stream type would put the stored value out of this check's reach, and
    a value out of reach is what the check exists to prevent.

    Takes source text rather than a path so the table below can run it
    over each form a constant can be written in. A scan that recognised
    only one form would go silent on an aggregate using another, and the
    found-at-least-one guard would still pass on the strength of a
    different aggregate that used the recognised form.
    """
    found: list[tuple[str, str | None]] = []
    for node in ast.parse(source).body:
        if isinstance(node, ast.Assign):
            targets: list[ast.expr] = list(node.targets)
            value: ast.expr | None = node.value
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
            value = node.value
        else:
            continue
        literal = (
            value.value
            if isinstance(value, ast.Constant) and isinstance(value.value, str)
            else None
        )
        found.extend(
            (target.id, literal)
            for target in targets
            if isinstance(target, ast.Name) and target.id.endswith(_SUFFIX)
        )
    return tuple(found)


@cache
def _declared_stream_types() -> dict[str, tuple[tuple[str, str | None], ...]]:
    """Every aggregate's stream-type constants, from git's tracked set.

    Keyed for every discovered aggregate, including those declaring
    nothing, so an aggregate with no constant is visible as an empty
    tuple rather than by being absent.
    """
    found: dict[str, list[tuple[str, str | None]]] = {a: [] for a in discovered_aggregates()}
    for path in tracked_python_files():
        parts = path.relative_to(KEEPER_ROOT).parts
        if len(parts) < 4 or parts[1] != "aggregates":
            continue
        aggregate = f"{parts[0]}/{parts[2]}"
        if aggregate in found:
            found[aggregate].extend(_stream_types_in_source(path.read_text(encoding="utf-8")))
    return {aggregate: tuple(constants) for aggregate, constants in found.items()}


def _declared_literals() -> dict[str, str]:
    """Aggregate to its single declared stream-type literal.

    An aggregate declaring none, more than one, or a non-literal is left
    out, which fails the equality below as a missing entry and fails the
    exactly-one rule with its own message.
    """
    literals: dict[str, str] = {}
    for aggregate, constants in _declared_stream_types().items():
        values = [value for _name, value in constants if value is not None]
        if len(values) == 1:
            literals[aggregate] = values[0]
    return literals


def test_the_stream_type_scan_finds_at_least_one_aggregate_and_one_constant() -> None:
    """Guard both sides: either one empty makes the comparison vacuous.

    No aggregates and the exactly-one rule below has an empty parameter
    set, which pytest reports as a skip. No constants found and the
    equality still runs, but against a derivation that has stopped
    working rather than against a tree that has changed.
    """
    assert discovered_aggregates(), "No aggregate folder found under any bounded context."
    assert any(_declared_stream_types().values()), (
        "No *_STREAM_TYPE constant found in any aggregate, so the pin below "
        "is comparing an empty derivation against a hand-written map."
    )


_SOURCE_FORMS: tuple[tuple[str, str, tuple[tuple[str, str | None], ...]], ...] = (
    ("plain", 'ACTOR_STREAM_TYPE = "Actor"', (("ACTOR_STREAM_TYPE", "Actor"),)),
    ("annotated", 'ACTOR_STREAM_TYPE: str = "Actor"', (("ACTOR_STREAM_TYPE", "Actor"),)),
    ("final", 'ACTOR_STREAM_TYPE: Final = "Actor"', (("ACTOR_STREAM_TYPE", "Actor"),)),
    ("computed", "ACTOR_STREAM_TYPE = _derive()", (("ACTOR_STREAM_TYPE", None),)),
    ("declared only", "ACTOR_STREAM_TYPE: str", (("ACTOR_STREAM_TYPE", None),)),
    ("other name", 'ACTOR_STREAM = "Actor"', ()),
    ("inside a function", 'def f() -> None:\n    ACTOR_STREAM_TYPE = "Actor"\n', ()),
)


@pytest.mark.parametrize(
    ("source", "expected"),
    [(source, expected) for _label, source, expected in _SOURCE_FORMS],
    ids=[label for label, _source, _expected in _SOURCE_FORMS],
)
def test_the_source_scan_reads_every_form_a_constant_can_take(
    source: str, expected: tuple[tuple[str, str | None], ...]
) -> None:
    """Run the scan over inputs of this table's choosing, not the tree's.

    The tree currently holds one constant in one form. A scan that only
    handled that form would look correct here forever and go quiet the
    first time somebody wrote `Final`, which is a silent loss of a
    subject rather than a failure.
    """
    assert _stream_types_in_source(source) == expected


@pytest.mark.parametrize("aggregate", discovered_aggregates())
def test_an_aggregate_declares_exactly_one_stream_type_constant(aggregate: str) -> None:
    constants = _declared_stream_types()[aggregate]
    assert len(constants) == 1, (
        f"{aggregate} declares {len(constants)} stream-type constants {constants}.\n"
        "Exactly one, because an aggregate is one stream type and the pin "
        "below is keyed by aggregate. An aggregate with none cannot be "
        "pinned at all, which is how a subject goes missing from a check "
        "that appears to range over every aggregate."
    )
    ((name, literal),) = constants
    assert literal is not None, (
        f"{aggregate} declares {name} as something other than a string literal.\n"
        "The stored value has to be readable from the source for the pin to "
        "mean anything. Computing it moves the wire format out of reach of "
        "every check in this file."
    )


def test_every_aggregate_pins_the_stream_type_it_writes_on_disk() -> None:
    declared = _declared_literals()
    assert declared == PINNED_STREAM_TYPES, (
        "Stream types no longer match their pins.\n"
        f"  in the tree: {declared}\n"
        f"  pinned here: {PINNED_STREAM_TYPES}\n"
        f"  unpinned:    {sorted(set(declared) - set(PINNED_STREAM_TYPES))}\n"
        f"  stale pins:  {sorted(set(PINNED_STREAM_TYPES) - set(declared))}\n\n"
        "A changed value means rows already written under the old name stop "
        "being found. Update the pin only alongside a migration that moves "
        "them. A new aggregate needs an entry here in the commit that lands it."
    )
