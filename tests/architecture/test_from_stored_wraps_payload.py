"""Every aggregate's deserializer wraps its errors, one message per event type.

A stored event row is deserialized back into an event class on every
replay. When a row is malformed the raw failure is a bare lookup or type
error thrown from somewhere inside a constructor call, carrying no hint
of which event type it came from. Error aggregators group by exception
type plus top frame, so every aggregate's malformed row collapses into
one undifferentiated issue.

The convention is that each arm wraps:

    case "EventType":
        try:
            return EventType(
                field=UUID(payload["field"]),
                ...
            )
        except (KeyError, TypeError, AttributeError) as exc:
            msg = f"Malformed EventType payload {payload!r}: {exc}"
            raise ValueError(msg) from exc

Raising from the original keeps the traceback, so nothing is lost by
wrapping. The shared helper `deserialize_or_raise` in
`keeper.infrastructure.slices.payload` does the same thing without the
boilerplate, and is accepted here as an equivalent spelling.

The check reads each deserializer body, finds every case arm, and looks
for a matching wrap message. It is shape-agnostic: inline try blocks and
the shared helper both satisfy it.
"""

import re
from pathlib import Path

import pytest

from tests.architecture.conftest import KEEPER_ROOT, tracked_python_files

pytestmark = pytest.mark.architecture


def _aggregate_events_files() -> list[Path]:
    """Every tracked events module sitting inside an aggregate folder.

    Filtered through the git-tracked set so an untracked work-in-progress
    aggregate is invisible here, matching what pre-commit would see.
    """
    return sorted(
        f
        for f in tracked_python_files()
        if f.stem == "events"
        and f.parent.parent.name == "aggregates"
        and f.parent.parent.parent.parent == KEEPER_ROOT
    )


def _qualified(p: Path) -> str:
    rel = p.relative_to(KEEPER_ROOT)
    return "keeper." + ".".join(rel.with_suffix("").parts)


def _from_stored_body(text: str) -> str | None:
    """Extract the deserializer body, stopping at the next top-level definition.

    The end-of-file arm matters. A module that puts the deserializer last,
    or omits the export list below it, would otherwise miss the regex and
    fall through to a skip, hiding the fact that no arm was checked.
    """
    pattern = r"^def from_stored.*?(?=^def [^_]|^__all__|^class |\Z)"
    m = re.search(pattern, text, re.DOTALL | re.MULTILINE)
    return m.group() if m else None


def test_the_wrap_rule_scan_finds_at_least_one_aggregate() -> None:
    """Guard the enumeration: an empty parameter set skips, it does not fail."""
    assert _aggregate_events_files(), (
        "No events module found inside any aggregate folder, so the wrap rule "
        "below ran against nothing."
    )


@pytest.mark.parametrize("events_file", _aggregate_events_files(), ids=_qualified)
def test_every_case_arm_wraps_its_payload_error_under_the_event_type_name(
    events_file: Path,
) -> None:
    text = events_file.read_text()
    body = _from_stored_body(text)
    if body is None:
        pytest.skip(f"{_qualified(events_file)}: no deserializer function")

    case_names = list(dict.fromkeys(re.findall(r'case "(\w+)":', body)))
    if not case_names:
        pytest.skip(f"{_qualified(events_file)}: no event-type arms found")

    unwrapped = [
        n
        for n in case_names
        if f"Malformed {n} payload" not in body
        and f'deserialize_or_raise(\n                "{n}"' not in body
        and f'deserialize_or_raise("{n}"' not in body
    ]
    assert not unwrapped, (
        f"{_qualified(events_file)}: these event-type arms do not wrap their "
        f"payload errors under the event-type name: {unwrapped}.\n"
        "Either apply the per-arm try block that names the event type in the "
        "message, or route the arm through deserialize_or_raise in "
        "keeper.infrastructure.slices.payload."
    )
