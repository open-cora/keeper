"""Mint the signing key, the JWKS and one bearer token per beamline.

    ./issue_tokens.py --root /local/cora 2-bm 7-bm 19-bm 32-id

Run it on the host the keeper runs on. It is idempotent in the part that
matters: an existing signing key is reused, never replaced, because
replacing it invalidates every token already handed out.

## What this is and is not

This is the smallest thing that answers "which beamline is calling". It is
not an identity provider. There is no discovery document, no token endpoint,
no refresh and no revocation: a token is minted here, copied to a beamline
once, and verified against a public key the keeper reads over loopback.

That is enough because the roster is four beamlines and a thinker, all
known in advance, and because the keeper's verifier asks only for a JWKS
and a signature. Revocation, if it is ever needed, is re-minting the key
and reissuing four files.

## Why the token is long-lived

A short expiry needs something to refresh it, and the thing that would do
the refreshing is the machinery this deliberately does not build. A year is
honest for a service account whose credential already sits in a home
directory at mode 600. The expiry is what makes it a token rather than a
password, and re-running this is what rotates it.

## Where each half goes

The private key never leaves this host. The JWKS is public by design and is
served on loopback only because that is the only reader. Each token goes to
exactly one beamline, into that account's own home, and a beamline can read
no other beamline's.
"""

from __future__ import annotations

import argparse
import base64
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid5

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

ISSUER = "https://cora.aps.anl.gov/idp/local"
"""Compared against the token's `iss` and never fetched.

A stable logical name rather than this host's address, so moving the keeper
does not invalidate every token. The verifier reaches only for the JWKS.
"""

AUDIENCE = "keeper-http"
HTTP_SURFACE_ID = UUID("00000000-0000-0000-0000-000000000020")
"""The arrival surface a conductor and a reporter both use.

The other two surfaces are the MCP ones. Each surface gets its own audience
string so a token minted for one cannot be replayed against another; only
the HTTP one is minted here, because nothing else has a caller yet.
"""

ALGORITHM = "ES256"
KEY_ID = "cora-local-1"
TOKEN_LIFETIME = timedelta(days=365)

_ACTOR_NAMESPACE = uuid5(NAMESPACE_URL, "https://github.com/open-cora/keeper/principals")


def actor_id(subject: str) -> UUID:
    """The principal id this subject maps to, derived rather than minted.

    Deriving it means re-running this produces the same binding, so a
    reissued token still points at the actor the record already names.
    """
    return uuid5(_ACTOR_NAMESPACE, subject)


def load_or_create_key(path: Path) -> ec.EllipticCurvePrivateKey:
    """Read the signing key, creating one only when there is none."""
    if path.exists():
        loaded = serialization.load_pem_private_key(path.read_bytes(), password=None)
        if not isinstance(loaded, ec.EllipticCurvePrivateKey):
            msg = f"{path} is not an EC private key, so it cannot sign {ALGORITHM}"
            raise TypeError(msg)
        return loaded

    key = ec.generate_private_key(ec.SECP256R1())
    path.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    path.chmod(0o600)
    return key


def jwks_document(key: ec.EllipticCurvePrivateKey) -> dict[str, object]:
    """The public half, in the shape `PyJWKClient` expects."""
    public_numbers = key.public_key().public_numbers()

    def to_b64(value: int) -> str:
        """A P-256 coordinate, as base64url with no padding, per RFC 7518."""
        return base64.urlsafe_b64encode(value.to_bytes(32, "big")).rstrip(b"=").decode()

    return {
        "keys": [
            {
                "kty": "EC",
                "crv": "P-256",
                "use": "sig",
                "alg": ALGORITHM,
                "kid": KEY_ID,
                "x": to_b64(public_numbers.x),
                "y": to_b64(public_numbers.y),
            }
        ]
    }


def mint(key: ec.EllipticCurvePrivateKey, subject: str) -> str:
    """One bearer token for one subject."""
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "iss": ISSUER,
            "sub": subject,
            "aud": AUDIENCE,
            "iat": int(now.timestamp()),
            "exp": int((now + TOKEN_LIFETIME).timestamp()),
        },
        key,
        algorithm=ALGORITHM,
        headers={"kid": KEY_ID},
    )


def provider_settings(subjects: list[str], jwks_url: str) -> list[dict[str, object]]:
    """The value `IDENTITY_PROVIDERS` carries, ready to be written as JSON."""
    return [
        {
            "issuer": ISSUER,
            "jwks_url": jwks_url,
            "audiences": {str(HTTP_SURFACE_ID): AUDIENCE},
            "allowed_algorithms": [ALGORITHM],
            "principal_kind": "service_account",
            # Loopback, so there is no transport to protect and nothing that
            # could be intercepted between the keeper and a file on its own
            # disk. Anything reachable off this host must be HTTPS instead.
            "allow_insecure_jwks_url": jwks_url.startswith("http://"),
            "subject_bindings": [
                {"subject": subject, "actor_id": str(actor_id(subject))} for subject in subjects
            ],
        }
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("subjects", nargs="+", help="one per caller, e.g. 2-bm")
    parser.add_argument("--root", type=Path, default=Path("/local/cora"))
    parser.add_argument("--jwks-url", default="http://127.0.0.1:8081/jwks.json")
    args = parser.parse_args(argv)

    etc = args.root / "etc"
    jwks_dir = args.root / "jwks"
    tokens_dir = etc / "tokens"
    for directory in (etc, jwks_dir, tokens_dir):
        directory.mkdir(parents=True, exist_ok=True)
    tokens_dir.chmod(0o700)

    key_path = etc / "signing-key.pem"
    existed = key_path.exists()
    key = load_or_create_key(key_path)
    print(f"signing key  {key_path}  ({'reused' if existed else 'created'})")

    jwks_path = jwks_dir / "jwks.json"
    jwks_path.write_text(json.dumps(jwks_document(key), indent=2) + "\n")
    print(f"jwks         {jwks_path}")

    for subject in args.subjects:
        token_path = tokens_dir / f"{subject}.token"
        token_path.write_text(mint(key, subject) + "\n")
        token_path.chmod(0o600)
        print(f"token        {token_path}  actor {actor_id(subject)}")

    settings_path = etc / "identity-providers.json"
    settings_path.write_text(
        json.dumps(provider_settings(args.subjects, args.jwks_url), indent=2) + "\n"
    )
    print(f"providers    {settings_path}")
    print()
    print("Each token goes to its own beamline, into that account's home at mode 600.")
    print("Nothing here should ever be copied to more than one beamline.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
