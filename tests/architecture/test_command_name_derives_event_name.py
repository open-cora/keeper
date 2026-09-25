"""A command class name mechanically derives the event class it emits.

The rule, for a slice that emits exactly one event:

    <Verb><Subject...>   ->   <Subject...><VerbPastParticiple>

Move the leading verb to the end, put it in the past participle, and
keep every other token unchanged AND IN ORDER.

The comparison is positional, deliberately. R3 in docs/reference/naming.md
is noun-LAST, and that page records it as the rule most often read
backwards. A check that accepted the tokens in any order would be blind
to exactly the mistake it exists to catch.

## Why derivability is worth pinning

The command and the event are the same fact told twice: once as a request
that may be refused, once as a record that cannot be. When the two names
drift apart, a reader has to carry a translation table to follow one
intent through the system, and every downstream artifact inherits the
ambiguity. Keep them derivable and a reader who knows either name knows
the other.

## Scope: slices that emit exactly one event

A slice emitting two events is emitting either a cross-aggregate pair or
a state-dependent choice between them. Neither has a single event for the
command name to derive, so both are out of scope. So are query slices,
which emit nothing.

## Resolving the command class

Three strategies, in order, because a slice's command module may declare
input value objects and result types beside the command itself, so "the
first class in the file" is not safe:

  1. the handler's command-label constant, when it names a class the
     command module declares
  2. the slice directory name in Pascal case, when that class exists
  3. the sole class in the command module

## Participle stemming

Regular -ed and -en, with the three English spelling adjustments:

    silent-e restoration     relocate  ->  Relocated
    consonant de-doubling    stop      ->  Stopped
    terminal y to i          deny      ->  Denied

Irregular forms are listed one at a time in `_IRREGULAR_STEMS`. Extend
that map rather than loosening the regular rules, which is how a stemmer
starts matching unrelated words.

## No exceptions

There is no allowlist. A pair that does not derive is renamed on one
side or the other, because that is the only fix that leaves a reader
able to guess either name from the other, which is the whole point.

An allowlist would be for a pair that cannot be renamed, and the reason
a name cannot be changed is always that something outside this
repository depends on it. Nothing does yet. When something does, the
exception arrives with the constraint that forced it.
"""

import ast
import re
from functools import cache
from pathlib import Path

import pytest

from tests.architecture.conftest import KEEPER_ROOT, tracked_python_files

pytestmark = pytest.mark.architecture

_TOKEN_RE = re.compile(r"[A-Z][a-z0-9]*")

_IRREGULAR_STEMS: dict[str, str] = {
    "held": "hold",
    "made": "make",
    "bound": "bind",
    "unbound": "unbind",
    "withdrawn": "withdraw",
    "taken": "take",
    "forgotten": "forget",
}
"""Past participle to base verb, for forms no suffix rule reaches."""


def _stems(token: str) -> frozenset[str]:
    """Every plausible base form of one capitalised token, lower-cased."""
    word = token.lower()
    if word in _IRREGULAR_STEMS:
        return frozenset({word, _IRREGULAR_STEMS[word]})
    out = {word}
    for suffix in ("ed", "en"):
        if word.endswith(suffix) and len(word) > len(suffix) + 1:
            base = word[: -len(suffix)]
            out |= {base, base + "e"}
            if len(base) > 2 and base[-1] == base[-2]:
                out.add(base[:-1])
            if base.endswith("i"):
                out.add(base[:-1] + "y")
    if word.endswith("e"):
        out.add(word[:-1])
    if word.endswith("y"):
        out.add(word[:-1] + "i")
    return frozenset(out)


def _derives(command: str, event: str) -> bool:
    """True when moving the command's leading verb to the end yields the event.

    The verb must be the LAST token of the event, not merely present in
    it. An earlier version scanned every position, which accepted
    `RegisterActor -> RegisteredActor`: the tokens are all there and the
    remainder matches, so only position tells the two apart. Position is
    the whole of R3.

    Tense is not checked here. `ActorRegister` has its verb last and
    passes this rule; `test_event_class_name_shape` is what refuses it
    for not being in the past. Splitting them keeps each failure message
    about one thing.
    """
    command_tokens = _TOKEN_RE.findall(command)
    event_tokens = _TOKEN_RE.findall(event)
    if not command_tokens or not event_tokens:
        return False
    verb, rest = command_tokens[0], command_tokens[1:]
    return bool(_stems(event_tokens[-1]) & _stems(verb)) and event_tokens[:-1] == rest


@cache
def _event_class_names() -> frozenset[str]:
    """Every class named by an event union across the tracked tree."""
    names: set[str] = set()
    for path in sorted(tracked_python_files()):
        if path.stem != "events" or "aggregates" not in path.parts:
            continue
        tree = ast.parse(path.read_text())
        union: list[str] | None = None
        for node in tree.body:
            if not isinstance(node, ast.Assign | ast.AnnAssign):
                continue
            target = node.target if isinstance(node, ast.AnnAssign) else node.targets[0]
            value = node.value
            if value is None or not isinstance(target, ast.Name):
                continue
            if target.id.endswith("Event"):
                union = [n.id for n in ast.walk(value) if isinstance(n, ast.Name)]
        if union is None:
            union = [n.name for n in tree.body if isinstance(n, ast.ClassDef)]
        names |= set(union)
    return frozenset(names)


@cache
def _command_slices() -> tuple[Path, ...]:
    """Slice directories that declare a command module, sorted by path."""
    return tuple(
        sorted(
            path.parent
            for path in tracked_python_files()
            if path.stem == "command" and path.parent.parent.name == "features"
        )
    )


def _slice_key(slice_dir: Path) -> str:
    """The bc/slice label used by the allowlists and by the test ids."""
    return f"{slice_dir.relative_to(KEEPER_ROOT).parts[0]}/{slice_dir.name}"


def _command_class(slice_dir: Path) -> str | None:
    """Resolve the slice's command class by the three documented strategies."""
    declared = [
        node.name
        for node in ast.parse((slice_dir / "command.py").read_text()).body
        if isinstance(node, ast.ClassDef)
    ]
    handler = slice_dir / "handler.py"
    if handler.exists():
        for node in ast.walk(ast.parse(handler.read_text())):
            if (
                isinstance(node, ast.Assign)
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id == "_COMMAND_NAME"
                and isinstance(node.value, ast.Constant)
                and node.value.value in declared
            ):
                return str(node.value.value)
    from_directory = "".join(word.capitalize() for word in slice_dir.name.split("_"))
    if from_directory in declared:
        return from_directory
    return declared[0] if len(declared) == 1 else None


def _emitted_event_classes(slice_dir: Path) -> frozenset[str]:
    """Event classes constructed anywhere inside one slice directory."""
    known = _event_class_names()
    found: set[str] = set()
    for path in sorted(tracked_python_files()):
        if not path.is_relative_to(slice_dir):
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in known
            ):
                found.add(node.func.id)
    return frozenset(found)


@cache
def _single_event_slices() -> dict[str, tuple[str, str]]:
    """Map bc/slice to its command class and its sole emitted event class."""
    out: dict[str, tuple[str, str]] = {}
    for slice_dir in _command_slices():
        emitted = _emitted_event_classes(slice_dir)
        command = _command_class(slice_dir)
        if command is None or len(emitted) != 1:
            continue
        out[_slice_key(slice_dir)] = (command, next(iter(emitted)))
    return out


def test_the_command_slice_scan_finds_at_least_one_single_event_slice() -> None:
    """Guard the enumeration: an empty parameter set skips, it does not fail."""
    assert _single_event_slices(), (
        "No slice resolves to a command class plus exactly one emitted event, so "
        "the derivation rule below ran against nothing."
    )


def test_every_command_slice_resolves_a_command_class() -> None:
    unresolved = [_slice_key(d) for d in _command_slices() if _command_class(d) is None]
    assert not unresolved, (
        "These slices declare a command module but no class could be resolved by "
        f"any of the three documented strategies: {unresolved}. Name the class "
        "after the slice directory, or have the handler's command-label constant "
        "name it, or reduce the command module to a single class."
    )


@pytest.mark.parametrize(
    ("command", "event"),
    [
        ("RegisterActor", "ActorRegistered"),
        ("DeactivateActor", "ActorDeactivated"),
        ("RelocateAsset", "AssetRelocated"),
        ("StopRun", "RunStopped"),
        ("DenyRequest", "RequestDenied"),
        ("HoldProcedure", "ProcedureHeld"),
        ("AmendClearanceScope", "ClearanceScopeAmended"),
    ],
    ids=lambda pair: str(pair),
)
def test_a_well_formed_pair_derives(command: str, event: str) -> None:
    """The stemming rules, on pairs this repository does not have.

    Three of these spellings are the documented adjustments: silent-e
    restoration, consonant de-doubling, and terminal y to i. One is an
    irregular. The last carries two subject tokens, to show the rule
    keeps every token after the verb rather than just the first.
    """
    assert _derives(command, event)


@pytest.mark.parametrize(
    ("command", "event", "why"),
    [
        ("RegisterActor", "ActorCreated", "different verb"),
        ("RegisterActor", "RegisteredActor", "verb still leading, noun last"),
        ("AmendClearanceScope", "ScopeClearanceAmended", "subject tokens reordered"),
        ("AmendClearanceScope", "ClearanceAmended", "a subject token dropped"),
        ("RegisterActor", "ActorRegisteredTwice", "a token nobody asked for"),
    ],
    ids=lambda triple: str(triple),
)
def test_a_malformed_pair_does_not_derive(command: str, event: str, why: str) -> None:
    """The negative cases, which nothing in this repository supplies.

    Every command slice here derives cleanly, so the rule above passes
    whatever `_derives` returns: hardwired to True it would be dead and
    green. These are the pairs that must be refused, and the fourth is
    the one the rule exists for. R3 is noun-LAST and is the rule most
    often read backwards, so a comparison that accepted the tokens in
    any order would be blind to exactly the mistake it was written to
    catch. `RegisteredActor` is that mistake: every token is present
    and only its position is wrong.

    Tense is deliberately absent from this list. `ActorRegister` has its
    verb last and passes here; the past-tense rule next door is what
    refuses it.
    """
    assert not _derives(command, event), f"{command} -> {event} should be refused: {why}"


@pytest.mark.parametrize("key", sorted(_single_event_slices()))
def test_a_command_name_derives_the_event_it_emits(key: str) -> None:
    command, event = _single_event_slices()[key]
    assert _derives(command, event), (
        f"{key}: the command {command!r} does not derive the event {event!r}. Move "
        "the leading verb to the end, put it in the past participle, and keep "
        "every other token unchanged and in order. Rename one side to match the "
        "other; there is no allowlist, because a pair a reader cannot derive is "
        "the cost this rule exists to refuse."
    )
