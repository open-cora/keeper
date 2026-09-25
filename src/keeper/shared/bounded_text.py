"""Trimmed-bounded-text validation for a value object's `value: str` field.

The shared shape across call sites is "trimmed string with a bounded
length", not "name": it backs name value objects and free-text reason
value objects alike, so the module is named for the shape rather than
for whichever family reaches for it first.

Two entry points. `validate_bounded_text` is the check itself.
`bounded_name` is a class decorator that installs the check, for the
common case of a frozen dataclass whose only field is `value: str`.

## Why a function and a decorator, not a base class

Each value object keeps three things a shared base would take away:

  - A distinct frozen dataclass type, so `isinstance` stays specific and
    a type checker keeps two name types apart at every annotation site.
  - A distinct error class, whose message can name the aggregate.
  - Its own `MAX_LENGTH` constant, read by both the value object and the
    Pydantic schema at the API boundary.

A shared base class would couple every aggregate to one type. A class
factory would weaken `isinstance`. A free function plus an optional
decorator gives the mechanism without the shared identity.

The function stays exported and backs the decorator internally. It is
also the right tool where the decorator does not fit:

  1. A value object with several fields, validating each inside one
     `__post_init__`.
  2. A bare string checked in place inside a decider, never wrapped in a
     value object at all.
  3. A value object with different rejection semantics, such as one that
     accepts empty-after-trim and rejects only on over-length.

## How a value object uses the decorator

`@bounded_name` goes ABOVE `@dataclass(frozen=True)`. Decorators apply
bottom-up, so `@dataclass` runs first and synthesizes `__init__`, then
`@bounded_name` wraps that synthesized `__init__`:

    @bounded_name(max_length=MAX_LENGTH, error_class=InvalidPolicyNameError)
    @dataclass(frozen=True)
    class PolicyName:
        value: str

The error class is constructed with the ORIGINAL untrimmed value, so its
message can quote what the caller actually sent.

## Why wrap `__init__` and not install `__post_init__`

`dataclasses._process_class` decides at DECORATION time whether to emit a
`self.__post_init__()` call in the synthesized `__init__`, based on
`hasattr(cls, '__post_init__')` at that moment. Installing
`__post_init__` afterwards through `setattr` is a silent no-op for a
class that did not define one before `@dataclass` ran.

Wrapping `__init__` is always sound instead: the synthesized `__init__`
is always present after `@dataclass(frozen=True)` and is always called at
construction. A hand-written `__post_init__` still chains correctly,
because the synthesized `__init__` calls it after the wrapped original
has stored the trimmed value.

## What survives the wrapping

Replacing a synthesized `__init__` is the kind of change that quietly
costs a class its equality or its pattern matching, so the list is
explicit. With `Callable[[type[T]], type[T]]` as the decorator's return
type, a type checker still sees:

  - the class as `type[C]` at every reference site, and `C('x')` as `C`
  - `.value` as `str`
  - `isinstance` narrowing inside `if isinstance(x, C):`
  - `__match_args__`, so `case C(value=v):` matches
  - an assignment to a frozen field flagged as `reportAttributeAccessIssue`
  - a missing or extra constructor argument flagged as `reportCallIssue`

The trimming itself is invisible to a type checker; it is a runtime
invariant, pinned by `tests/unit/test_bounded_text.py` along with the
equality, hash, repr and pattern-matching behaviour above.

## Decoration-time guards

`bounded_name` raises `TypeError` while the class is being decorated when
the class is not a dataclass (usually `@dataclass` placed below it by
mistake) or when it has no `value` field. Both fire at import, so neither
mistake can ship.
"""

from collections.abc import Callable
from dataclasses import is_dataclass
from typing import TypeVar

T = TypeVar("T")


def validate_bounded_text(
    value: str,
    *,
    max_length: int,
    error_class: type[Exception],
) -> str:
    """Trim, length-check, return the trimmed value, or raise `error_class`.

    Raises `error_class(value)` (the original untrimmed value) if the
    trimmed result is empty or exceeds `max_length`. Otherwise returns
    the trimmed string for the VO to install on itself.
    """
    trimmed = value.strip()
    if not trimmed or len(trimmed) > max_length:
        raise error_class(value)
    return trimmed


def bounded_name(
    *,
    max_length: int,
    error_class: type[Exception],
) -> Callable[[type[T]], type[T]]:
    """Wrap a frozen-dataclass `value: str` VO with trim + length-check.

    Apply ABOVE `@dataclass(frozen=True)`:

        @bounded_name(max_length=POLICY_NAME_MAX_LENGTH, error_class=InvalidPolicyNameError)
        @dataclass(frozen=True)
        class PolicyName:
            value: str

    The decorator wraps the dataclass-synthesized `__init__` so that
    every construction of `PolicyName(...)` trims the input, raises
    `error_class(value)` with the ORIGINAL untrimmed value on empty
    or over-length, and stores the trimmed value via the synthesized
    `__init__`'s normal `object.__setattr__('value', ...)` call site.
    The class object is returned in place (no subclass, no factory),
    so `isinstance`, `__match_args__`, `__eq__`, `__hash__`, and
    `__repr__` are all preserved.

    Raises `TypeError` at decoration time if the decorated class is
    not a dataclass (`@dataclass` belongs ABOVE `@bounded_name` so
    that `@dataclass` runs first and `@bounded_name` sees a real
    dataclass) or if the class lacks a `value` field.
    """

    def decorate(cls: type[T]) -> type[T]:
        if not is_dataclass(cls):
            raise TypeError(
                f"@bounded_name must be applied above @dataclass on {cls.__name__}; "
                f"saw a non-dataclass class. Decorator order: "
                f"@bounded_name OUTER, @dataclass(frozen=True) INNER."
            )
        if "value" not in cls.__dataclass_fields__:  # pyright: ignore[reportAttributeAccessIssue]
            raise TypeError(f"@bounded_name requires a `value` field on {cls.__name__}")

        original_init = cls.__init__

        def wrapped_init(self: T, value: str) -> None:
            trimmed = validate_bounded_text(value, max_length=max_length, error_class=error_class)
            original_init(self, trimmed)  # pyright: ignore[reportCallIssue]

        cls.__init__ = wrapped_init  # pyright: ignore[reportAttributeAccessIssue]
        return cls

    return decorate


__all__ = ["bounded_name", "validate_bounded_text"]
