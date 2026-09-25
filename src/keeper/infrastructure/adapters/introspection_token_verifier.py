"""`IntrospectionTokenVerifier`: RFC 7662 token introspection adapter.

Implements `keeper.infrastructure.ports.TokenVerifier` for IdPs that
issue opaque tokens, Globus Auth being the common case, which is
opaque by default unless the JWT v3 scope is requested at registration.

## How it works

  1. Receive opaque token from the route-layer middleware.
  2. Look up the cache: if `(issuer, token_hash)` is fresh (< TTL),
     return the cached `VerifiedPrincipal`.
  3. Otherwise POST to the IdP's `introspection_url` with HTTP Basic
     auth (`client_id` + `client_secret`) per RFC 7662 §2.1.
  4. Parse the response JSON; if `active=true`, build a
     `VerifiedPrincipal` and cache. If `active=false`, raise
     `InvalidTokenError("introspection_inactive", ...)`.
  5. Network / 5xx failures raise `IntrospectionUnavailableError`
     (→ 503 + Retry-After by the route layer). Distinct from
     "token is invalid" so operators see the difference.

## Cache discipline

A per-token-hash LRU with a short TTL (default 30s, configurable via
`Settings.introspection_cache_ttl_seconds`). Why hash-the-token-not-
the-token: a bug that prints the cache key shouldn't leak secrets.
Why 30s default: balances IdP RPS against the worst-case "token just
got revoked" window, short enough that a revoke ≤ 30s later sees
the change on the next request, long enough that 100-request
bursts fan out to ~4 IdP calls not 100.

## Anti-pattern guard

No introspection without per-token cache: the bare adapter
constructor refuses TTL=0 with a `ValueError`. Test-only
adapters set TTL=1 if they need fast cache turnover.

## Concurrent-request coalescing, DEFERRED

Two concurrent requests with the same opaque token currently both
miss the cache and both call introspection. A `dogpile`-style
single-flight per-token-hash lock would dedupe; not in v1 scope
because the 30s TTL bounds the fan-out and Globus rate limits are
generous enough. Watch item if introspection latency p99 climbs.
"""

import asyncio
import hashlib
import time
from collections import OrderedDict
from uuid import UUID

import httpx
from pydantic import SecretStr

from keeper.infrastructure.adapters.jwt_token_verifier import safe_map_subject
from keeper.infrastructure.logging import get_logger
from keeper.infrastructure.ports.token_verifier import (
    IntrospectionUnavailableError,
    InvalidTokenError,
    PrincipalKind,
    SubjectMapper,
    VerifiedPrincipal,
)

_log = get_logger(__name__)

_MAX_CACHE_ENTRIES = 1024
"""Hard cap on per-verifier cache size. With
30s TTL + per-token-hash keys, an attacker presenting N unique
tokens would otherwise grow the dict unbounded. OrderedDict-based
LRU eviction keeps memory bounded; entries past their TTL are
swept opportunistically on read."""


class _CacheEntry:
    __slots__ = ("expires_at", "principal")

    def __init__(self, principal: VerifiedPrincipal, expires_at: float) -> None:
        self.principal = principal
        self.expires_at = expires_at


class IntrospectionTokenVerifier:
    """RFC 7662 opaque-token verifier for a single IdP.

    One instance per registered issuer. The `IdpRegistry`
    routes opaque-shape tokens to the deployment's configured
    introspection verifier (typically one per deployment, the
    primary IdP).
    """

    def __init__(
        self,
        *,
        issuer: str,
        introspection_url: str,
        client_id: str,
        client_secret: str | SecretStr,
        audience_for_surface: dict[UUID, str],
        subject_mapper: SubjectMapper,
        cache_ttl_seconds: int = 30,
        http_client: httpx.AsyncClient | None = None,
        principal_kind: PrincipalKind = "human",
        allow_insecure_introspection_url: bool = False,
    ) -> None:
        """Construct an introspection verifier bound to one IdP issuer.

        `client_id` + `client_secret` authenticate the keeper to the IdP's
        introspection endpoint via HTTP Basic (RFC 7662 §2.1).
        These are the keeper's own credentials at the IdP, distinct from
        the user-token being introspected. Accept either a raw `str`
        or a `pydantic.SecretStr`; either way the value is wrapped
        in `SecretStr` so it never shows in `__repr__` / tracebacks
        / accidental log dumps.

        `cache_ttl_seconds`: per-token cache lifetime. TTL=0 is
        forbidden (no introspection without cache); pass 1 only for
        test-determinism scenarios. Default 30s.

        `http_client`: optional pre-configured `httpx.AsyncClient`
        (test override). Default: lazy-constructed with separate
        connect/read/write/pool timeouts (slowloris defense, F7).

        `principal_kind`: usually `"human"`; per-IdP override for
        machine-only IdPs (for example a dedicated service-account issuer).

        `allow_insecure_introspection_url`: production MUST be False
        (default). Test/dev fixtures using `http://127.0.0.1:...`
        opt in by passing True. Otherwise the keeper's client_secret would
        traverse plain HTTP basic-auth and an attacker MITMing the
        introspection POST captures the keeper's IdP credentials.
        """
        if cache_ttl_seconds < 1:
            msg = (
                f"IntrospectionTokenVerifier for issuer={issuer!r}: cache_ttl_seconds "
                "must be >= 1 (no introspection without a per-token cache). "
                "Pass 1 only for test-determinism cases."
            )
            raise ValueError(msg)
        if not introspection_url.startswith("https://") and not allow_insecure_introspection_url:
            msg = (
                f"IntrospectionTokenVerifier for issuer={issuer!r}: introspection_url "
                f"must be HTTPS (got scheme={introspection_url.split(':')[0]!r}). "
                "Pass allow_insecure_introspection_url=True only for test/dev "
                "fixtures: HTTP Basic over plain HTTP leaks client_secret to "
                "a network attacker."
            )
            raise ValueError(msg)
        self._issuer = issuer
        self._introspection_url = introspection_url
        self._client_id = client_id
        self._client_secret: SecretStr = (
            client_secret if isinstance(client_secret, SecretStr) else SecretStr(client_secret)
        )
        self._audience_for_surface = audience_for_surface
        self._subject_mapper = subject_mapper
        self._cache_ttl = cache_ttl_seconds
        self._http_client = http_client
        self._owned_client = http_client is None
        self._principal_kind = principal_kind
        # OrderedDict-based LRU: bounded growth + per-write eviction of
        # expired entries first, then oldest insertions.
        self._cache: OrderedDict[str, _CacheEntry] = OrderedDict()
        self._cache_lock = asyncio.Lock()

    @property
    def issuer(self) -> str:
        return self._issuer

    async def aclose(self) -> None:
        """Close the owned HTTP client. No-op if a client was injected."""
        if self._owned_client and self._http_client is not None:
            await self._http_client.aclose()
            self._http_client = None

    def _cache_key(self, token: str, expected_aud_str: str) -> str:
        """Composite cache key: SHA256(token) bound to the per-Surface
        audience string.

        Without binding `aud` into the key, a token introspected once
        for Surface A returns the cached principal for Surface B
        within TTL, bypassing per-Surface authz. Same shape that
        `idempotency_keys` required. The token half is SHA256-hashed
        so cache dumps never expose the bearer."""
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        return f"{token_hash}|{expected_aud_str}"

    def _client(self) -> httpx.AsyncClient:
        if self._http_client is None:
            # Separate connect/read/write/pool timeouts. Connect fails fast on dead hosts;
            # read budget covers a normally-responsive IdP.
            self._http_client = httpx.AsyncClient(
                timeout=httpx.Timeout(connect=2.0, read=5.0, write=2.0, pool=2.0),
                limits=httpx.Limits(max_connections=20, max_keepalive_connections=5),
            )
        return self._http_client

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

        cache_key = self._cache_key(token, expected_aud_str)
        now = time.monotonic()

        async with self._cache_lock:
            entry = self._cache.get(cache_key)
            if entry is not None and entry.expires_at > now:
                # Touch (LRU promotion) and return.
                self._cache.move_to_end(cache_key)
                return entry.principal

        try:
            response = await self._client().post(
                self._introspection_url,
                data={"token": token, "token_type_hint": "access_token"},
                auth=(self._client_id, self._client_secret.get_secret_value()),
            )
        except httpx.HTTPError as exc:
            _log.warning(
                "introspection.network_error",
                issuer=self._issuer,
                error=str(exc),
            )
            raise IntrospectionUnavailableError(self._issuer, str(exc)) from exc

        if response.status_code >= 500:
            _log.warning(
                "introspection.server_error",
                issuer=self._issuer,
                status_code=response.status_code,
            )
            raise IntrospectionUnavailableError(self._issuer, f"http {response.status_code}")
        if response.status_code != 200:
            # 4xx from the IdP, typically the keeper's introspection
            # credentials are wrong, OR the IdP rejects the request
            # shape. Map to InvalidTokenError so the caller sees 401,
            # not 503; the cause is upstream config, not transient.
            raise InvalidTokenError(
                "malformed",
                f"introspection returned http {response.status_code}",
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise InvalidTokenError("malformed", f"introspection response not JSON: {exc}") from exc

        if not payload.get("active"):
            raise InvalidTokenError(
                "introspection_inactive",
                "IdP returned active=false",
            )

        # Audience check on introspected payload. RFC 7662 §2.2 makes
        # `aud` an OPTIONAL response field, when the IdP does include
        # it, we strict-match; when absent, we trust the IdP's policy
        # that issued this opaque token for our resource. (Operators
        # who need stricter binding should request JWT-v3 scope and
        # use the JWT path instead.)
        aud = payload.get("aud")
        if aud is not None:
            aud_match = False
            if isinstance(aud, str):
                aud_match = aud == expected_aud_str
            elif isinstance(aud, list):
                aud_match = expected_aud_str in aud
            if not aud_match:
                raise InvalidTokenError(
                    "wrong_audience",
                    f"introspection aud={aud!r} != expected {expected_aud_str!r}",
                )

        iss = str(payload.get("iss", self._issuer))
        if iss != self._issuer:
            raise InvalidTokenError(
                "wrong_issuer",
                f"introspection iss={iss!r} != expected {self._issuer!r}",
            )

        subject = str(payload.get("sub", ""))
        if not subject:
            raise InvalidTokenError("malformed", "introspection response missing 'sub' claim")

        principal_id, kind = await safe_map_subject(self._subject_mapper, self._issuer, subject)
        scopes = _parse_scopes_claim(payload.get("scope"))

        principal = VerifiedPrincipal(
            principal_id=principal_id,
            subject=subject,
            issuer=self._issuer,
            kind=kind or self._principal_kind,
            scopes=scopes,
        )

        # Cap cache freshness by the token's declared `exp` if present.
        # RFC 7662 section 2.2 may return `exp` as a numeric POSIX
        # timestamp; convert to monotonic-clock relative seconds.
        wall_now = time.time()
        cache_expires_at = now + self._cache_ttl
        exp_claim = payload.get("exp")
        if isinstance(exp_claim, (int, float)) and exp_claim > wall_now:
            cache_expires_at = min(cache_expires_at, now + (exp_claim - wall_now))

        async with self._cache_lock:
            self._cache[cache_key] = _CacheEntry(
                principal=principal,
                expires_at=cache_expires_at,
            )
            self._cache.move_to_end(cache_key)
            self._evict_locked(now)

        return principal

    def _evict_locked(self, now: float) -> None:
        """Drop expired entries first, then LRU-trim to max size.
        Caller MUST hold `self._cache_lock`."""
        if len(self._cache) <= _MAX_CACHE_ENTRIES:
            # Cheap path: just sweep expired entries.
            expired = [k for k, e in self._cache.items() if e.expires_at <= now]
            for key in expired:
                del self._cache[key]
            return
        # Over cap: same sweep, then LRU trim.
        expired = [k for k, e in self._cache.items() if e.expires_at <= now]
        for key in expired:
            del self._cache[key]
        while len(self._cache) > _MAX_CACHE_ENTRIES:
            self._cache.popitem(last=False)


def _parse_scopes_claim(raw: object) -> frozenset[str]:
    """Normalize the OAuth `scope` (RFC 6749 §3.3) / `scp` claim shape.

    See `keeper.infrastructure.adapters.jwt_token_verifier._parse_scopes_claim`:
    duplicated here intentionally so this module doesn't pull on the
    JWT module just for a 5-line helper (rule-of-two; promote if a
    third caller arrives).
    """
    if isinstance(raw, str):
        return frozenset(raw.split())
    if isinstance(raw, list):
        items: list[str] = [str(item) for item in raw]  # type: ignore[misc]
        return frozenset(items)
    return frozenset()


__all__ = ["IntrospectionTokenVerifier"]
