"""Mint the signing key, the JWKS and one bearer token per caller.

    ./issue_tokens.py --root /local/cora conductor-19-bm reporter-19-bm thinker

A subject is `<role>-<beamline>` for anything running at a beamline and
the bare role for anything central, which is the convention the deploy
README sets out and the reason this takes callers rather than beamlines.
The same string names the configuration, the log and, through
`{subject}.token`, the credential.

Run it on the host the keeper runs on. It is idempotent: an existing
signing key is reused, never replaced, because replacing it invalidates
every token already handed out, and an existing token is kept for the
same reason one scale down. `--rotate <subject>` is how a caller gets a
new one, and only that caller.

The keeping matters more than it looks. The installer runs this on every
deploy, and while a re-run merely added a credential that was harmless.
Now that a new token retires the subject's older ones, a re-run that
minted unconditionally would refuse every beamline at once on an
unrelated deploy, which is the facility-wide outage this whole mechanism
exists to avoid.

## What this is and is not

This is the smallest thing that answers "which beamline is calling". It is
not an identity provider. There is no discovery document, no token endpoint
and no refresh: a token is minted here, copied to a beamline once, and
verified against a public key the keeper reads over loopback.

That is enough because the roster is a handful of callers known in
advance, and because the keeper's verifier asks only for a JWKS and a
signature.

## Revocation, which costs one line here because nothing can be asked

A provider that can be asked about a token answers revocation by being
asked, which is what RFC 7662 introspection is for and what the keeper
already has a verifier for. This one publishes keys and answers nothing,
so there is no question to put to it.

What it can do instead is say, in the configuration it writes, that a
subject's tokens issued before some instant no longer count. Each
binding carries the mint time of the token issued with it, so handing a
caller a new credential retires its old ones and nobody else's. Without
that the only lever is re-minting the signing key, which retires every
caller at every beamline to retire one.

Its resolution is a second, because that is what `iat` is defined in.
Two tokens minted for one subject inside the same second cannot be told
apart, so the earlier one survives. That bounds what this is for: it
retires a credential issued at some earlier time, which is the case
that arises, and it is not a way to pick between two tokens minted
together.

## Why the token is long-lived

A short expiry needs something to refresh it, and the thing that would do
the refreshing is the machinery this deliberately does not build. A year is
honest for a service account whose credential already sits in a home
directory at mode 600. The expiry is what makes it a token rather than a
password, and `--rotate` is what replaces one before it runs out.

## Where each half goes

The private key never leaves this host. The JWKS is public by design and is
served on loopback only because that is the only reader. Each token goes to
exactly one caller, into that account's own home. Two callers at one
beamline share an account and so share a home, which is why splitting them
is attribution rather than isolation.
"""

from __future__ import annotations

import argparse
import base64
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
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


def mint(key: ec.EllipticCurvePrivateKey, subject: str, issued_at: datetime) -> str:
    """One bearer token for one subject, minted at a caller-chosen instant.

    The instant is passed rather than read here so that the same value
    can be written into this subject's binding as the point its older
    credentials stop being accepted. Reading the clock twice would put
    the retirement a moment after the token it was meant to spare, and
    the new token would refuse itself.
    """
    return jwt.encode(
        {
            "iss": ISSUER,
            "sub": subject,
            "aud": AUDIENCE,
            "iat": int(issued_at.timestamp()),
            "exp": int((issued_at + TOKEN_LIFETIME).timestamp()),
        },
        key,
        algorithm=ALGORITHM,
        headers={"kid": KEY_ID},
    )


def minted_at(token: str) -> datetime | None:
    """When an existing token on this host says it was issued.

    Read without verifying, which is sound only because of where it is
    read from: this script's own output, on the keeper's own disk, at
    mode 600. It is not a trust decision, it is recovering a value this
    script wrote.

    None for a token minted before tokens carried the claim. Such a
    subject gets no retirement time rather than being locked out of a
    credential it is currently using, which leaves it exactly as it was
    until somebody rotates it on purpose.
    """
    body = token.strip().split(".")[1]
    body += "=" * (-len(body) % 4)
    claims: dict[str, Any] = json.loads(base64.urlsafe_b64decode(body))
    issued = claims.get("iat")
    if not isinstance(issued, int | float):
        return None
    return datetime.fromtimestamp(int(issued), UTC)


def provider_settings(
    subjects: list[str], jwks_url: str, issued_at: dict[str, datetime]
) -> list[dict[str, object]]:
    """The value `IDENTITY_PROVIDERS` carries, ready to be written as JSON.

    Each binding carries the instant that subject's token was minted,
    which the verifier reads as the point its older tokens stop being
    accepted. That is what makes issuing a token to one caller retire
    that caller's previous ones, and only that caller's.

    This provider publishes keys and answers no questions about a
    token, so there is nothing to introspect and the retirement has to
    travel in the configuration. A provider that can be asked leaves
    this unset and is asked instead.
    """
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
                {
                    "subject": subject,
                    "actor_id": str(actor_id(subject)),
                    **(
                        {"not_before": issued_at[subject].isoformat()}
                        if subject in issued_at
                        else {}
                    ),
                }
                for subject in subjects
            ],
        }
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "subjects", nargs="+", help="one per caller, e.g. conductor-19-bm or thinker"
    )
    parser.add_argument("--root", type=Path, default=Path("/local/cora"))
    parser.add_argument(
        "--rotate",
        action="append",
        metavar="SUBJECT",
        help=(
            "mint this subject a new token and retire its old ones. Repeatable. "
            "Every subject is still listed so the provider file stays complete; "
            "this only says which of them get a new credential"
        ),
    )
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

    rotating = set(args.rotate or [])
    unknown = sorted(rotating - set(args.subjects))
    if unknown:
        parser.error(f"--rotate names {unknown}, which is not among the subjects given")

    issued_at: dict[str, datetime] = {}
    for subject in args.subjects:
        token_path = tokens_dir / f"{subject}.token"
        if token_path.exists() and subject not in rotating:
            kept = minted_at(token_path.read_text())
            if kept is not None:
                issued_at[subject] = kept
            print(f"token        {token_path}  actor {actor_id(subject)}  (kept)")
            continue

        # Whole seconds, because the claim is written as an integer and
        # the binding has to hold the same instant the token says it was
        # minted at. A retirement a fraction later than its own token
        # refuses it.
        at = datetime.now(UTC).replace(microsecond=0)
        issued_at[subject] = at
        token_path.write_text(mint(key, subject, at) + "\n")
        token_path.chmod(0o600)
        print(f"token        {token_path}  actor {actor_id(subject)}  (new, retires earlier ones)")

    settings_path = etc / "identity-providers.json"
    settings_path.write_text(
        json.dumps(provider_settings(args.subjects, args.jwks_url, issued_at), indent=2) + "\n"
    )
    print(f"providers    {settings_path}")
    print()
    print("Each token goes to its own caller, into that account's home at mode 600.")
    print("Nothing here should ever be copied to more than one beamline.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
