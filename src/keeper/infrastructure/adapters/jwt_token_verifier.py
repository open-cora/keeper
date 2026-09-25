"""`JwtTokenVerifier`: local JWKS-based JWT verification.

Implements `keeper.infrastructure.ports.TokenVerifier` for IdPs that
issue self-describing JWT access tokens, the industry default:
Microsoft Entra, Google, Auth0, Okta, AWS Cognito, Helmholtz AAI,
ORCID-via-OIDC, and any IdP following RFC 9068 ("OAuth 2.0 Access
Tokens in JWT").

## Library choice

PyJWT (`pyjwt[crypto]` dep) is the one library dependency for
edge-auth.
The `[crypto]` extra pulls `cryptography` for RS256/ES256, every
real-world IdP uses one of these two. AROC does NOT roll its own
signature verify or JOSE parsing; that's the library's whole job.

## Per-issuer one `PyJWKClient`

PyJWT's `PyJWKClient` caches the JWKS in-memory and refetches on
kid-miss. We instantiate one per registered issuer at startup and
keep them alive for the process lifetime, repeated `.get_signing_key_from_jwt(token)`
calls hit the cache, and a token signed with a fresh key triggers
one refetch then resumes from cache.

Cache TTL is governed by PyJWT's internal `lifespan` (default 5 min);
we leave it at the default. The TTL is not what makes rotation safe. The
kid-miss refetch is: a key the cache has never seen forces one fetch
whatever the TTL says, so a rotation is picked up at the first token
signed with the new key rather than up to five minutes later.

## What `verify()` checks (in order)

  1. Parse token + extract unverified header (`alg`, `kid`, `typ`).
  2. Reject if `alg` not in the configured whitelist (RFC 9068 §4
     specifically calls out `alg=none` rejection; we go further and
     pin a small whitelist per-issuer).
  3. Fetch the signing key for `kid` from the JWKS (cached + on-miss-refetch).
  4. PyJWT verifies signature + standard claims (`exp`, `nbf`, `iat`,
     `iss`, `aud`) with explicit `algorithms`, `audience`, `issuer`
     options. NO `options={"verify_signature": False}` anywhere.
  5. Map `sub` claim to a `principal_id` via the injected
     `SubjectMapper`, which is injected: the verifier never reaches
     into whatever owns that mapping.
  6. Return `VerifiedPrincipal(principal_id, sub, iss, kind, scopes)`.

Any failure raises `InvalidTokenError` with a specific reason code
so route-layer logs distinguish modes (bad_signature vs expired vs
wrong_audience).

## What we do NOT check

- Token **revocation**. JWT-AT has no native revocation (RFC 9068 §5,
  RFC 6819 §5.2.1). Mitigation = short token TTL (5-15 min,
  passive-revocation pattern per RFC 6819 §5.1.5.3). When a
  must-revoke-immediately need lands, that subject moves to
  introspection-required.
- Token **scope→capability** mapping. Edge-auth ships without
  scope-aware authorization; scopes flow into `VerifiedPrincipal.scopes`
  for future use.
"""

from typing import get_args
from uuid import UUID

import jwt
from jwt import PyJWKClient

from keeper.infrastructure.ports.token_verifier import (
    InvalidTokenError,
    PrincipalKind,
    SubjectMapper,
    VerifiedPrincipal,
)
from keeper.shared.reserved_ids import NIL_SENTINEL_ID, SYSTEM_PRINCIPAL_ID

_VALID_KINDS: frozenset[str] = frozenset(get_args(PrincipalKind))


class JwtTokenVerifier:
    """RFC 9068 JWT access-token verifier for a single IdP.

    One instance per registered issuer. The `IdpRegistry`
    holds the dict of `iss → JwtTokenVerifier` and routes by token's `iss`
    claim.
    """

    def __init__(
        self,
        *,
        issuer: str,
        jwks_url: str,
        audience_for_surface: dict[UUID, str],
        subject_mapper: SubjectMapper,
        allowed_algorithms: list[str],
        principal_kind: PrincipalKind = "human",
        allow_insecure_jwks_url: bool = False,
    ) -> None:
        """Construct a verifier bound to one IdP issuer.

        `issuer`: expected `iss` claim on every token (exact match,
        no trailing-slash leniency).
        `jwks_url`: `https://<idp>/.well-known/jwks.json` or
        equivalent; `PyJWKClient` fetches + caches keys from here.
        `audience_for_surface`: Surface UUID → audience string the
        IdP signs into the token's `aud` claim for that Surface.
        `subject_mapper`: async callable resolving (iss, sub) to
        (principal_id, kind). See SubjectMapper docstring.
        `allowed_algorithms`: explicit whitelist. RFC 9068 §4
        rejects `alg=none`; we go further with a small list. Typical:
        `["RS256", "ES256"]`. Pinning the list per-issuer matches
        the IdP's actual capabilities + locks out algorithm-
        confusion attacks at the verifier layer.
        `principal_kind`: defaults `"human"`. Per-IdP override for
        deployments where the entire IdP issues only service-account
        tokens (for example a CI-only IdP).

        `allow_insecure_jwks_url`: production MUST be False (default).
        Test/dev fixtures using `http://127.0.0.1:...` JWKS endpoints
        opt in by passing True. Without HTTPS, an attacker who MITMs
        the JWKS fetch owns all signature verification for this issuer.
        Localhost is implicitly safe, but explicit opt-in beats implicit
        allow.
        """
        if not allowed_algorithms:
            msg = (
                f"JwtTokenVerifier for issuer={issuer!r} requires a non-empty "
                "allowed_algorithms whitelist (no alg=none). "
                "Explicit > implicit."
            )
            raise ValueError(msg)
        # Strip + lowercase so " None ", "NONE", "noNe" are all caught.
        if "none" in (a.strip().lower() for a in allowed_algorithms):
            msg = (
                f"JwtTokenVerifier for issuer={issuer!r}: "
                "allowed_algorithms must not include 'none'."
            )
            raise ValueError(msg)
        if not jwks_url.startswith("https://") and not allow_insecure_jwks_url:
            msg = (
                f"JwtTokenVerifier for issuer={issuer!r}: jwks_url must be HTTPS "
                f"(got scheme={jwks_url.split(':')[0]!r}). Pass "
                "allow_insecure_jwks_url=True only for test/dev fixtures "
                "."
            )
            raise ValueError(msg)
        self._issuer = issuer
        self._audience_for_surface = audience_for_surface
        self._subject_mapper = subject_mapper
        self._algorithms = list(allowed_algorithms)
        self._principal_kind = principal_kind
        self._jwks_client = PyJWKClient(jwks_url)

    @property
    def issuer(self) -> str:
        return self._issuer

    async def verify(
        self,
        token: str,
        *,
        expected_audience: UUID,
    ) -> VerifiedPrincipal:
        expected_aud_str = self._audience_for_surface.get(expected_audience)
        if expected_aud_str is None:
            raise InvalidTokenError(
                "wrong_audience",
                f"no aud configured for surface={expected_audience}",
            )

        try:
            signing_key = self._jwks_client.get_signing_key_from_jwt(token)
        except jwt.PyJWKClientError as exc:
            raise InvalidTokenError("bad_signature", f"jwks lookup failed: {exc}") from exc
        except jwt.DecodeError as exc:
            raise InvalidTokenError("malformed", str(exc)) from exc

        try:
            claims = jwt.decode(
                token,
                signing_key.key,
                algorithms=self._algorithms,
                audience=expected_aud_str,
                issuer=self._issuer,
                options={"require": ["exp", "iss", "aud", "sub"]},
            )
        except jwt.ExpiredSignatureError as exc:
            raise InvalidTokenError("expired", str(exc)) from exc
        except jwt.ImmatureSignatureError as exc:
            raise InvalidTokenError("not_yet_valid", str(exc)) from exc
        except jwt.InvalidAudienceError as exc:
            raise InvalidTokenError("wrong_audience", str(exc)) from exc
        except jwt.InvalidIssuerError as exc:
            raise InvalidTokenError("wrong_issuer", str(exc)) from exc
        except jwt.InvalidAlgorithmError as exc:
            raise InvalidTokenError("unsupported_algorithm", str(exc)) from exc
        except jwt.InvalidSignatureError as exc:
            raise InvalidTokenError("bad_signature", str(exc)) from exc
        except jwt.MissingRequiredClaimError as exc:
            raise InvalidTokenError("malformed", str(exc)) from exc
        except jwt.InvalidTokenError as exc:
            raise InvalidTokenError("malformed", str(exc)) from exc

        subject = str(claims["sub"])
        principal_id, kind = await safe_map_subject(self._subject_mapper, self._issuer, subject)
        scopes = _parse_scopes_claim(claims.get("scope") or claims.get("scp"))
        return VerifiedPrincipal(
            principal_id=principal_id,
            subject=subject,
            issuer=self._issuer,
            kind=kind or self._principal_kind,
            scopes=scopes,
        )


def _parse_scopes_claim(raw: object) -> frozenset[str]:
    """Normalize the OAuth `scope` (RFC 6749 §3.3) / `scp` (Microsoft)
    claim shape to `frozenset[str]`.

    Accepts: space-separated string (standard), list of strings
    (Microsoft Entra v2 sometimes), None / missing / other shape →
    empty frozenset.
    """
    if isinstance(raw, str):
        return frozenset(raw.split())
    if isinstance(raw, list):
        items: list[str] = [str(item) for item in raw]  # type: ignore[misc]
        return frozenset(items)
    return frozenset()


async def safe_map_subject(
    mapper: SubjectMapper, issuer: str, subject: str
) -> tuple[UUID, PrincipalKind]:
    """Call the SubjectMapper with defense-in-depth.

    Wraps any exception from the mapper as
    `InvalidTokenError("unknown_subject", ...)` so route-layer logs
    distinguish "the subject isn't registered" from generic 500s.
    Rejects two principal ids outright. `SYSTEM_PRINCIPAL_ID` is the
    unauthenticated fallback identity, so a bearer token resolving to it
    would let any holder of a valid token act as the system account.
    `NIL_SENTINEL_ID` means "unspecified", which is a mapper bug rather
    than an identity. The two were the same UUID until the constants
    were split, when one nil check covered both by accident; they are
    checked separately now so neither relies on the other's value.

    Also rejects invalid `kind` values, which would
    silently degrade `service_account` → `human` via the
    `kind or principal_kind` fallback.

    Shared helper used by both JWT and Introspection adapters.
    """
    try:
        principal_id, kind = await mapper(issuer, subject)
    except InvalidTokenError:
        raise
    except Exception as exc:
        raise InvalidTokenError("unknown_subject", f"subject mapper raised: {exc}") from exc
    if principal_id == SYSTEM_PRINCIPAL_ID:
        raise InvalidTokenError(
            "unknown_subject",
            "subject mapper returned the system principal (would escalate to SYSTEM)",
        )
    if principal_id == NIL_SENTINEL_ID:
        raise InvalidTokenError(
            "unknown_subject",
            "subject mapper returned the nil sentinel (unspecified is not an identity)",
        )
    if kind not in _VALID_KINDS:
        raise InvalidTokenError(
            "malformed",
            f"subject mapper returned kind={kind!r}; expected one of {sorted(_VALID_KINDS)}",
        )
    return principal_id, kind


__all__ = ["JwtTokenVerifier"]
