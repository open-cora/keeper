"""The open-scheme identifier pair for a concept AROC references but does not model."""

import pytest

from keeper.shared.identifier import (
    IDENTIFIER_SCHEME_MAX_LENGTH,
    IDENTIFIER_VALUE_MAX_LENGTH,
    Identifier,
    InvalidIdentifierError,
)

pytestmark = pytest.mark.unit


def test_identifier_trims_both_halves_on_construction() -> None:
    identifier = Identifier(scheme="  doi  ", value="  10.1234/abc  ")
    assert (identifier.scheme, identifier.value) == ("doi", "10.1234/abc")


@pytest.mark.parametrize("scheme", ["", "   ", "s" * (IDENTIFIER_SCHEME_MAX_LENGTH + 1)])
def test_identifier_refuses_a_scheme_that_is_blank_or_too_long(scheme: str) -> None:
    with pytest.raises(InvalidIdentifierError) as caught:
        Identifier(scheme=scheme, value="v")
    assert caught.value.field == "scheme"


@pytest.mark.parametrize("value", ["", "   ", "v" * (IDENTIFIER_VALUE_MAX_LENGTH + 1)])
def test_identifier_refuses_a_value_that_is_blank_or_too_long(value: str) -> None:
    with pytest.raises(InvalidIdentifierError) as caught:
        Identifier(scheme="doi", value=value)
    assert caught.value.field == "value"


def test_identifier_error_carries_the_untrimmed_input() -> None:
    """A whitespace-only rejection is undiagnosable once the whitespace is gone."""
    with pytest.raises(InvalidIdentifierError) as caught:
        Identifier(scheme="   ", value="v")
    assert caught.value.value == "   "


def test_identifier_measures_length_after_trimming() -> None:
    padded = f"  {'v' * IDENTIFIER_VALUE_MAX_LENGTH}  "
    assert Identifier(scheme="doi", value=padded).value == "v" * IDENTIFIER_VALUE_MAX_LENGTH


def test_identifier_is_hashable_so_it_can_key_a_lookup() -> None:
    assert len({Identifier("doi", "a"), Identifier("doi", "a"), Identifier("ror", "a")}) == 2


def test_identifier_accepts_any_scheme_because_the_vocabulary_lives_on_the_carrier() -> None:
    """Closed-enum discipline is the carrier aggregate's job, deliberately not this one's."""
    assert Identifier(scheme="something-nobody-has-registered", value="x").scheme
