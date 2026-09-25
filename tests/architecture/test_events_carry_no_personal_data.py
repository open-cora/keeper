"""No event payload carries a field that names a person.

The record is append-only. `events` is INSERT-only at the database role
level, so a value written into a payload is there for the life of the
system: it cannot be corrected, redacted, or erased on request. Every
other table in this schema can be rewritten; this one is the exception,
and that is the whole reason it is trustworthy.

Personal data and an append-only table are therefore incompatible. Not
awkward together, incompatible: the one thing personal data must always
be is deletable.

## What this checks, and on which side

Two sides, because they can disagree:

  - the FIELDS each event dataclass declares, which is what a reader
    sees and what a future author copies from
  - the KEYS the payload builder writes, which is what actually lands
    in the row

A field can be renamed on its way into the payload, and a payload
builder can add a key no dataclass declares. Checking only the first
would miss a literal `"email"` written straight into the dict.

## Why a deny-list and not a judgement

A rule cannot tell whether a value is personal; it can only tell what a
field is called. So this is a list of names that are personal wherever
they appear, and it is deliberately short. A long list catches more and
gets suppressed; this one should be arguable line by line.

`name`, bare, is on it. Not because every name is a person's, but
because it is the field this repository removed on purpose and the one
most likely to come back by habit. A qualified name is a different
thing and passes: `command_name`, `stream_type_name`, `method_name` are
about machinery, not people.

## When this fires on something legitimate

There is no allowlist, because here the escape hatch is almost never
the right answer. The deny-list matches exact names, so a field holding
the name of a THING already passes: `method_name` and `policy_name` are
fine and only bare `name` is not. A field that trips this rule is
either misnamed, and gets qualified, or personal, and moves out of the
payload into a table that can be deleted. See
docs/reference/conventions.md.
"""

import ast
import re
from pathlib import Path

import pytest

from tests.architecture.conftest import KEEPER_ROOT, tracked_python_files

pytestmark = pytest.mark.architecture

PERSONAL_FIELD_NAMES: frozenset[str] = frozenset(
    {
        # What a person is called.
        "name",
        "full_name",
        "first_name",
        "last_name",
        "given_name",
        "family_name",
        "surname",
        "display_name",
        "nickname",
        "initials",
        # How a person is reached.
        "email",
        "email_address",
        "phone",
        "phone_number",
        "mobile",
        "address",
        "home_address",
        "postcode",
        "postal_code",
        # What a person is registered as, by someone else.
        "ssn",
        "national_id",
        "passport_number",
        "tax_id",
        "badge_number",
        "orcid",
        # What a person is.
        "date_of_birth",
        "birth_date",
        "gender",
        "nationality",
        # Where a person was.
        "ip_address",
    }
)
"""Field names that mean a person, wherever they appear.

Exact matches, not substrings. A substring rule would reject
`command_name` and `stream_id` and be switched off within a week, which
is worse than a rule that misses `emailAddress`.

This list is short on purpose and every entry should be arguable on its
own. Add one when a real field would have slipped past, never
speculatively: a name nothing was ever going to be called costs a line
here and buys nothing.
"""


_SNAKE = re.compile(r"(?<!^)(?=[A-Z])")


def _events_files() -> list[Path]:
    """Tracked events modules sitting inside an aggregate folder."""
    return sorted(
        path
        for path in tracked_python_files()
        if path.stem == "events" and "aggregates" in path.parts
    )


def _qualified(p: Path) -> str:
    return "keeper." + ".".join(p.relative_to(KEEPER_ROOT).with_suffix("").parts)


def _declared_fields(tree: ast.Module) -> list[tuple[str, str]]:
    """Every `(ClassName, field)` on a module-level dataclass."""
    out: list[tuple[str, str]] = []
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        for stmt in node.body:
            if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                out.append((node.name, stmt.target.id))
    return out


def _payload_keys(tree: ast.Module) -> list[tuple[str, str]]:
    """Every `(function, key)` string key written into a dict in the module.

    Ranges over dict literals anywhere in a function body rather than
    only the returned one, because a builder that assembles the payload
    in a local and returns it later is the same fact written differently.
    """
    out: list[tuple[str, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        for inner in ast.walk(node):
            if not isinstance(inner, ast.Dict):
                continue
            for key in inner.keys:
                if isinstance(key, ast.Constant) and isinstance(key.value, str):
                    out.append((node.name, key.value))
    return out


def _offends(field: str) -> bool:
    return _SNAKE.sub("_", field).lower() in PERSONAL_FIELD_NAMES


def test_the_personal_data_scan_finds_at_least_one_aggregate() -> None:
    """Guard the enumeration: an empty parameter set skips, it does not fail."""
    assert _events_files(), (
        "No events module found inside any aggregate folder, so the personal-data "
        "rule below ran against nothing."
    )


@pytest.mark.parametrize("path", _events_files(), ids=_qualified)
def test_no_event_declares_a_field_that_names_a_person(path: Path) -> None:
    module = _qualified(path)
    offenders = [
        f"{module}:{cls}.{field}"
        for cls, field in _declared_fields(ast.parse(path.read_text()))
        if _offends(field)
    ]
    assert not offenders, (
        "Event classes declare fields that name a person:\n  "
        + "\n  ".join(offenders)
        + "\n\nEvents are append-only and personal data has to be erasable, so "
        "the two cannot share a row. Move the value to a table that can be "
        "deleted and keep the subject's id in the payload. If the field is not "
        "personal despite its name, qualify it: `method_name` passes "
        "where `name` does not."
    )


@pytest.mark.parametrize("path", _events_files(), ids=_qualified)
def test_no_payload_builder_writes_a_key_that_names_a_person(path: Path) -> None:
    """The other side: what the dict actually gets, not what the class declares.

    A field renamed on its way into the payload, or a key written as a
    literal with no field behind it, is invisible to the check above and
    lands in the row just the same.
    """
    module = _qualified(path)
    offenders = [
        f"{module}:{func}[{key!r}]"
        for func, key in _payload_keys(ast.parse(path.read_text()))
        if _offends(key)
    ]
    assert not offenders, (
        "Payload builders write keys that name a person:\n  "
        + "\n  ".join(offenders)
        + "\n\nThis is the side that reaches the database. A key here is in the "
        "log whether or not any dataclass declares it."
    )


def test_the_deny_list_leaves_machinery_field_names_alone() -> None:
    """The false positives that would get this rule switched off.

    Every name here is one an event legitimately carries. A rule that
    rejected them would be suppressed within a week, and a suppressed
    rule protects nothing, so the looseness is pinned rather than left
    to whoever next edits the list.
    """
    benign = (
        "actor_id",
        "occurred_at",
        "command_name",
        "event_type",
        "stream_id",
        "schema_version",
        "method_name",
        "policy_name",
        "correlation_id",
        "reason",
    )
    rejected = [field for field in benign if _offends(field)]
    assert not rejected, (
        f"The deny-list rejects field names that are about machinery: {rejected}. "
        "A qualified name is not a person. Narrow PERSONAL_FIELD_NAMES rather "
        "than allowlisting each site."
    )


def test_the_deny_list_reaches_a_camel_case_field_name() -> None:
    """`emailAddress` is the same field as `email_address` to this rule.

    Nothing in this repository is written that way, so without this the
    normalisation could be deleted and every test would still pass.
    """
    assert _offends("emailAddress")
    assert _offends("fullName")


def test_the_rule_catches_a_personal_field_on_a_source_that_has_one() -> None:
    """Run the machinery against something that offends, because nothing here does.

    Every entry in the deny-list is verified the moment a real field
    trips it, and no real field does: that is the point of the rule and
    also its blind spot. Deleting `name` from the list would break no
    other test in this repository until somebody put a name back on an
    event, which is exactly the moment the rule was supposed to have
    been watching.

    So the check is given a synthetic module to look at. This exercises
    `_declared_fields` and `_offends` together, not set membership, and
    it fails if either the entry or the matching goes away.
    """
    source = (
        "@dataclass(frozen=True)\n"
        "class ThingHappened:\n"
        "    thing_id: UUID\n"
        "    name: str\n"
        "    email: str\n"
        "    occurred_at: datetime\n"
    )
    caught = [field for _cls, field in _declared_fields(ast.parse(source)) if _offends(field)]
    assert caught == ["name", "email"], (
        f"The rule saw {caught} on a source declaring a name and an email beside "
        "two innocent fields. Both should be caught and neither of the others."
    )


def test_the_rule_catches_a_personal_key_on_a_payload_that_writes_one() -> None:
    """The payload side of the same blind spot, exercised the same way."""
    source = (
        "def to_payload(event):\n"
        "    return {\n"
        '        "thing_id": str(event.thing_id),\n'
        '        "email": event.email,\n'
        "    }\n"
    )
    caught = [key for _func, key in _payload_keys(ast.parse(source)) if _offends(key)]
    assert caught == ["email"]
