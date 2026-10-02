"""Retiring one caller's tokens without retiring everybody's.

Every other check in the JWT verifier reads the token, a public key and
the clock. That is what makes verification fast, and it is also why
nothing else there can take a credential back: none of those inputs
changes when one leaks. The only lever without this is the signing key,
and rolling it refuses every caller at every beamline at once.

So one input is added that is per subject and cheap: the instant that
subject's older tokens stop counting, compared against the `iat` the
token already carries. Issuing a token sets it, which is what makes
re-issuing a caller's token retire that caller's previous ones.

The trap these tests exist for is the token refusing itself. The
retirement and the token it is meant to spare are minted together, and
a retirement a fraction of a second later than its own token locks out
the caller it was just issued to.
"""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec

from keeper.infrastructure.adapters.jwt_token_verifier import JwtTokenVerifier
from keeper.infrastructure.ports.token_verifier import InvalidTokenError, PrincipalKind

pytestmark = pytest.mark.unit

ISSUER = "https://idp.example.com/local"
"""A stand-in. The deployed issuer is a value an operator configures."""

AUDIENCE = "keeper-http"
SURFACE = UUID("00000000-0000-0000-0000-000000000020")
ACTOR = UUID("67280012-733a-54ef-a527-60c87b291610")
RETIREMENT = datetime(2026, 10, 2, 9, 38, 53, tzinfo=UTC)


def _token(key: ec.EllipticCurvePrivateKey, subject: str, issued_at: datetime | None) -> str:
    claims: dict[str, Any] = {
        "iss": ISSUER,
        "sub": subject,
        "aud": AUDIENCE,
        "exp": int((datetime.now(UTC) + timedelta(days=1)).timestamp()),
    }
    if issued_at is not None:
        claims["iat"] = int(issued_at.timestamp())
    return jwt.encode(claims, key, algorithm="ES256", headers={"kid": "test-signing-key"})


async def _mapper(_issuer: str, _subject: str) -> tuple[UUID, PrincipalKind]:
    return ACTOR, "service_account"


def _verifier(
    key: ec.EllipticCurvePrivateKey,
    monkeypatch: pytest.MonkeyPatch,
    retired_before: dict[str, datetime],
) -> JwtTokenVerifier:
    """A verifier whose key lookup is answered locally.

    The constructor builds a client that fetches the key set over the
    network. Replacing it is what keeps these about the retirement rule
    rather than about reaching an endpoint.
    """
    verifier = JwtTokenVerifier(
        issuer=ISSUER,
        jwks_url="https://idp.example.com/jwks.json",
        audience_for_surface={SURFACE: AUDIENCE},
        subject_mapper=_mapper,
        allowed_algorithms=["ES256"],
        principal_kind="service_account",
        retired_before=retired_before,
    )
    public = key.public_key()

    def signing_key(_token: str) -> SimpleNamespace:
        return SimpleNamespace(key=public)

    monkeypatch.setattr(
        verifier, "_jwks_client", SimpleNamespace(get_signing_key_from_jwt=signing_key)
    )
    return verifier


@pytest.fixture
def key() -> ec.EllipticCurvePrivateKey:
    return ec.generate_private_key(ec.SECP256R1())


async def test_a_token_minted_before_its_subjects_retirement_is_refused(
    key: ec.EllipticCurvePrivateKey, monkeypatch: pytest.MonkeyPatch
) -> None:
    verifier = _verifier(key, monkeypatch, {"19-bm": RETIREMENT})
    stale = _token(key, "19-bm", RETIREMENT - timedelta(days=2))

    with pytest.raises(InvalidTokenError) as refusal:
        await verifier.verify(stale, expected_audience=SURFACE)

    assert refusal.value.reason == "revoked"


async def test_a_token_minted_at_the_retirement_instant_is_still_accepted(
    key: ec.EllipticCurvePrivateKey, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The trap: a retirement must not refuse the token it was issued with.

    Both are written in one pass of the issuing script, so the
    retirement is the new token's own `iat`. Any comparison stricter
    than this locks out the caller at the moment its credential is
    replaced, which is every rotation.
    """
    verifier = _verifier(key, monkeypatch, {"19-bm": RETIREMENT})
    fresh = _token(key, "19-bm", RETIREMENT)

    principal = await verifier.verify(fresh, expected_audience=SURFACE)

    assert principal.principal_id == ACTOR


async def test_a_subject_with_no_retirement_time_is_unaffected(
    key: ec.EllipticCurvePrivateKey, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The ordinary case, and every issuer that can be asked directly."""
    verifier = _verifier(key, monkeypatch, {})
    old = _token(key, "7-bm", datetime(2025, 1, 1, tzinfo=UTC))

    principal = await verifier.verify(old, expected_audience=SURFACE)

    assert principal.principal_id == ACTOR


async def test_a_retired_subject_presenting_a_token_without_an_iat_is_refused(
    key: ec.EllipticCurvePrivateKey, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fail closed, because the open direction accepts what was retired.

    `iat` is not required of every token, so its absence is ordinary
    for a subject nobody has retired. For a subject somebody has, the
    comparison cannot be made, and allowing it would accept exactly the
    credential the retirement was declared about as long as it omits
    the claim.
    """
    verifier = _verifier(key, monkeypatch, {"19-bm": RETIREMENT})
    undated = _token(key, "19-bm", None)

    with pytest.raises(InvalidTokenError) as refusal:
        await verifier.verify(undated, expected_audience=SURFACE)

    assert refusal.value.reason == "revoked"


async def test_retiring_one_subject_leaves_another_subjects_token_working(
    key: ec.EllipticCurvePrivateKey, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The whole point, and the thing rolling the signing key cannot do.

    One beamline's credential is retired while the others keep working.
    Without this the only lever is the key every token is signed with,
    and pulling it means a 401 at every station until a new token
    reaches each of them by hand.
    """
    verifier = _verifier(key, monkeypatch, {"19-bm": RETIREMENT})
    minted_before_the_retirement = RETIREMENT - timedelta(days=2)

    with pytest.raises(InvalidTokenError):
        await verifier.verify(
            _token(key, "19-bm", minted_before_the_retirement), expected_audience=SURFACE
        )

    spared = await verifier.verify(
        _token(key, "7-bm", minted_before_the_retirement), expected_audience=SURFACE
    )
    assert spared.subject == "7-bm"
