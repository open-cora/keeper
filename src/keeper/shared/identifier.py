"""Shared identifier value object.

`Identifier(scheme, value)` is the open-scheme anti-corruption pair for an
upstream concept this system references but does NOT model as a first-class
aggregate. The scheme names the issuing authority; the value is opaque to it.

Closed-vocabulary discipline lives on the CARRIER aggregate, never on this
value object. A carrier that admits only a fixed set of schemes enforces that
closed-enum invariant in its own `__post_init__` BEFORE delegating here;
`Identifier` never sees the closed-enum context.

A standards-specific identifier family (a persistent-identifier tuple with a
closed scheme enum, an instance-tier alternate identifier, and so on) belongs
with the aggregate that carries it, until a third independent carrier makes it
genuinely shared. At that point hoist the value object and its construction
errors here, and leave the carrier-bound errors at their carriers.
"""

from dataclasses import dataclass

IDENTIFIER_SCHEME_MAX_LENGTH = 50
IDENTIFIER_VALUE_MAX_LENGTH = 200


class InvalidIdentifierError(ValueError):
    """An Identifier's scheme or value is empty, whitespace-only, or too long.

    The `value` attribute carries the ORIGINAL untrimmed input so callers
    can diagnose whitespace-only rejections without losing the offending
    characters.
    """

    def __init__(self, field: str, value: str) -> None:
        super().__init__(f"Identifier {field} is invalid (got: {value!r})")
        self.field = field
        self.value = value


@dataclass(frozen=True, slots=True)
class Identifier:
    """Open-scheme identifier pair.

    Free-form scheme; per-site closed-enum discipline lives at the carrier
    aggregate, not on this value object.
    """

    scheme: str
    value: str

    def __post_init__(self) -> None:
        scheme_trimmed = self.scheme.strip()
        if not scheme_trimmed or len(scheme_trimmed) > IDENTIFIER_SCHEME_MAX_LENGTH:
            raise InvalidIdentifierError(field="scheme", value=self.scheme)
        value_trimmed = self.value.strip()
        if not value_trimmed or len(value_trimmed) > IDENTIFIER_VALUE_MAX_LENGTH:
            raise InvalidIdentifierError(field="value", value=self.value)
        object.__setattr__(self, "scheme", scheme_trimmed)
        object.__setattr__(self, "value", value_trimmed)


__all__ = [
    "IDENTIFIER_SCHEME_MAX_LENGTH",
    "IDENTIFIER_VALUE_MAX_LENGTH",
    "Identifier",
    "InvalidIdentifierError",
]
