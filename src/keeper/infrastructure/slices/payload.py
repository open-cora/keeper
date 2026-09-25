"""Wrap a `from_stored` builder so a malformed payload raises one shape.

Every aggregate deserialises stored events with a `match stored.event_type:`
dispatch whose arms each build an event dataclass out of a raw payload dict.
A payload that does not match its declared shape raises `KeyError`,
`TypeError` or `AttributeError` from deep inside the builder, naming the
field rather than the event. `deserialize_or_raise` catches those and
re-raises `ValueError("Malformed {event_type} payload ...")`, so a caller
can match on the event type without knowing which field failed.

## Why a free function, not a decorator or a base class
The shared shape across call sites is the try / wrap / re-raise body, not
the dispatch or the builder expression. A free function lets each arm stay
a one-line call:

    case "ThingRegistered":
        return deserialize_or_raise(
            "ThingRegistered",
            lambda: ThingRegistered(
                thing_id=UUID(payload["thing_id"]),
                occurred_at=datetime.fromisoformat(payload["occurred_at"]),
                kind=ThingKind(payload["kind"]),
            ),
            extra=(ValueError,),
        )

A decorator on the arm is impossible, since Python match-case arms cannot
be decorated. A base class would force every aggregate's event union
through an inheritance chain for no structural benefit.

## Why `extra` is a keyword tuple
An arm that calls `SomeEnum(payload[k])` inline raises `ValueError` rather
than the three caught by default, and `ValueError` cannot be caught
unconditionally here because it is also what this function raises. Those
arms opt in with `extra=(ValueError,)`; the default empty tuple keeps the
common arm quiet.

## Why the payload is NOT echoed in the message
Echoing the raw payload into the `ValueError` string leaks field values
into log aggregators, where they outlive the request that produced them
and are correlatable against anything else those logs hold. Assert only on the
`"Malformed {event_type}"` substring, never on an echoed payload, so that
log hygiene stays separable from test breakage.

## Why `message_suffix` is keyword-only
A versioned event whose old and new arms both deserialise needs the two
messages told apart. The suffix is placed AFTER the `payload` token so the
`Malformed <EventType> payload` prefix stays stable for callers matching
on it.
"""

from collections.abc import Callable, Iterable, Sequence

from keeper.infrastructure.ports.event_store import StoredEvent


def deserialize_or_raise[EventT](
    event_type: str,
    builder: Callable[[], EventT],
    *,
    extra: tuple[type[BaseException], ...] = (),
    message_suffix: str = "",
) -> EventT:
    """Run `builder` and re-raise stored-event decoding failures as `ValueError`.

    Catches `KeyError`, `TypeError`, `AttributeError`, plus any
    classes in `extra`; re-raises a `ValueError` carrying the
    canonical `"Malformed {event_type} payload{message_suffix}: {exc}"`
    text. The original exception is chained via `__cause__`.

    The raw payload is intentionally NOT included in the message;
    see module docstring for the PII-hygiene rationale.
    """
    try:
        return builder()
    except (KeyError, TypeError, AttributeError, *extra) as exc:
        msg = f"Malformed {event_type} payload{message_suffix}: {exc}"
        raise ValueError(msg) from exc


def deserialize_vo_or_raise[VoT](
    vo_type: str,
    builder: Callable[[], VoT],
    *,
    extra: tuple[type[BaseException], ...] = (),
    raise_as: type[ValueError] = ValueError,
) -> VoT:
    """Run `builder` and re-raise nested-VO decoding failures as `raise_as`.

    Catches `KeyError`, `TypeError`, `AttributeError`, plus any
    classes in `extra`; re-raises `raise_as` (default `ValueError`)
    carrying the canonical `"Malformed {vo_type} payload: {exc}"`
    text. The original exception is chained via `__cause__`.

    The raw payload is intentionally NOT included in the message;
    see module docstring for the PII-hygiene rationale (same as
    `deserialize_or_raise`).

    The `raise_as` knob is for a value object whose own helper already
    raises a typed subclass of `ValueError`. Without it the subclass is
    flattened to the generic wrap and the caller loses the distinction it
    went to the trouble of making; with it, the outer `from_stored` arm
    absorbs the typed error through `extra=(ValueError,)` and the type
    survives to the event-type wrap layer.
    """
    try:
        return builder()
    except (KeyError, TypeError, AttributeError, *extra) as exc:
        msg = f"Malformed {vo_type} payload: {exc}"
        raise raise_as(msg) from exc


def find_first_event(
    stored_events: Iterable[StoredEvent],
    event_type: str,
) -> StoredEvent | None:
    """The FIRST event of `event_type` in a loaded stream, or None.

    Scans from the head and early-exits on the first hit. Correct where
    the wanted record is a genesis one, which by definition cannot be
    superseded by a later event of the same type.
    """
    for event in stored_events:
        if event.event_type == event_type:
            return event
    return None


def find_last_event(
    stored_events: Sequence[StoredEvent],
    event_type: str,
) -> StoredEvent | None:
    """The LAST event of `event_type` in a loaded stream, or None.

    Scans from the tail. Correct where a later event of the same type
    SUPERSEDES an earlier one, which is the case for any record a failed
    attempt can leave behind and a retry can re-emit with different
    content. Takes a `Sequence` rather than an `Iterable` because
    reversing needs a known end.
    """
    for event in reversed(stored_events):
        if event.event_type == event_type:
            return event
    return None


__all__ = [
    "deserialize_or_raise",
    "deserialize_vo_or_raise",
    "find_first_event",
    "find_last_event",
]
