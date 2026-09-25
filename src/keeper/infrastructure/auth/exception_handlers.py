"""HTTP exception handlers for the edge-auth errors.

Two handlers are registered globally on the FastAPI app at startup
via `register_auth_exception_handlers(app)`:

  - `InvalidTokenError` -> HTTP 401 + RFC 6750 §3 WWW-Authenticate
    challenge. The `reason` short-string (for example "bad_signature",
    "expired", "wrong_audience") goes into the `error=` parameter
    of the challenge so clients can distinguish without parsing
    free-form text. The `error_description=` carries the (already
    operator-safe) `detail` field. Both values are quoted-string-
    escaped per RFC 7235 §2.2 to keep header parsers happy.
    Also includes `resource_metadata="<url>"` per RFC 9728 §4.1 so
    clients can discover where to acquire a fresh token.

  - `IntrospectionUnavailableError` -> HTTP 503 + `Retry-After: 5`.
    Distinct from the 401 path so operators can grep logs for
    "their token is bad" vs "our IdP introspection endpoint is
    down." The retry hint is conservative (5 seconds) so clients
    back off briefly rather than hammering the verifier during an
    upstream outage.

## Why a module-level register function

The BC convention: each BC's `register_<bc>_routes(app)` registers
its exception handlers. Auth errors are infrastructure-level (no
BC owns them), so they live in a parallel function called once at
app construction. Mirrors the `register_protected_resource_metadata_route`
shape next to it in main.py.

## Why not raise typed HTTPExceptions directly

The middleware (`BearerAuthMiddleware`) and the parser
(`_extract_bearer_token`) raise typed domain errors
(`InvalidTokenError`, `IntrospectionUnavailableError`) so:

  - The token verifier port stays HTTP-agnostic (it could be
    consumed by a future non-HTTP surface).
  - The error -> response mapping lives in one place per the BC
    handler convention.
  - Tests for the verifier + middleware can assert on typed errors
    without coupling to FastAPI's HTTPException internals.

Per RFC 6750 §3.1 the WWW-Authenticate header is REQUIRED on a 401
response that the resource server has authenticated as a bearer
challenge -- the BC convention's `JSONResponse(status_code=401)`
shape would omit this. So this module constructs the response
directly (not via `HTTPException`) to control headers.
"""

from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from keeper.infrastructure.auth._routed_path import _routed_path
from keeper.infrastructure.logging import get_logger
from keeper.infrastructure.ports import IntrospectionUnavailableError, InvalidTokenError

_log = get_logger(__name__)

# The "realm" parameter is REQUIRED in RFC 6750 §3 challenges. The keeper
# is one realm; future multi-realm setups (multiple deployments
# behind a single gateway) override via a settings-driven helper.
_REALM = "keeper"

# Per RFC 9728 §4.1, the WWW-Authenticate challenge MAY carry a
# `resource_metadata` parameter pointing at the protected-resource
# metadata document. The keeper's lives at this fixed path (registered by
# `register_protected_resource_metadata_route`).
_RESOURCE_METADATA_PATH = "/.well-known/oauth-protected-resource"


def _quote(value: str) -> str:
    """RFC 7235 §2.2 auth-param quoted-string: backslash-escape `"` and `\\`,
    then strip control chars (RFC 7230 §3.2.6 forbids CTL in quoted-string).

    an IdP-controlled `subject` claim (which can
    reach `error_description` via `InvalidTokenError.detail` on the
    `unknown_subject` path) that contains CR / LF / NUL would split
    the WWW-Authenticate header and enable response-header injection.
    Strip CTL chars (0x00-0x1F + 0x7F minus SP / HTAB) BEFORE the
    backslash-escape so a crafted token can never break out.

    HTAB is preserved (legal in quoted-string per RFC 7230 §3.2.6
    `qdtext` whitespace allowance). SP is preserved (also legal).
    Every other CTL becomes a single space, visible-but-safe.
    """
    sanitized_chars: list[str] = []
    for ch in value:
        code = ord(ch)
        if code in (0x09, 0x20):  # HTAB + SP
            sanitized_chars.append(ch)
        elif code < 0x20 or code == 0x7F:  # CTL minus the two allowed
            sanitized_chars.append(" ")
        else:
            sanitized_chars.append(ch)
    sanitized = "".join(sanitized_chars)
    escaped = sanitized.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _bearer_challenge(*, error: str, error_description: str) -> str:
    """Format an RFC 6750 §3 Bearer challenge header value.

    Carries realm + error + error_description + resource_metadata.
    The order of auth-params is not significant per the RFC; the
    layout below matches the order clients most commonly grep for
    in failed-auth logs (error first).
    """
    parts = [
        f"Bearer realm={_quote(_REALM)}",
        f"error={_quote(error)}",
        f"error_description={_quote(error_description)}",
        f"resource_metadata={_quote(_RESOURCE_METADATA_PATH)}",
    ]
    return ", ".join(parts)


def missing_bearer_challenge() -> str:
    """Format the bearer challenge for a missing-bearer 401.

    Per RFC 6750 §3, when no credentials are presented the challenge
    SHOULD omit `error=` (which is for failed verification of a
    presented token). Just realm + resource_metadata so the client
    knows where to fetch a token. Public helper so the routing
    layer's Mode-2 401 path can format the header without
    re-implementing the realm / metadata-path constants.
    """
    parts = [
        f"Bearer realm={_quote(_REALM)}",
        f"resource_metadata={_quote(_RESOURCE_METADATA_PATH)}",
    ]
    return ", ".join(parts)


async def _handle_invalid_token(request: Request, exc: Exception) -> JSONResponse:
    """Map `InvalidTokenError` to HTTP 401 with RFC 6750 challenge.

    the response body + error_description carry
    only the closed-set `reason` short-code (for example "bad_signature",
    "unknown_subject", "wrong_audience"). The free-form `detail`
    field stays in the structured log line ONLY -- it can contain
    IdP-controlled values (subject string for `unknown_subject`,
    audience strings for `wrong_audience`) that would enable
    enumeration of registered subjects / IdP federation surface if
    echoed back to unauthenticated callers.
    """
    # Pyright sees Exception in the FastAPI handler signature; the
    # registered class IS InvalidTokenError so the cast is safe.
    assert isinstance(exc, InvalidTokenError)  # type-narrow for pyright
    _log.info(
        "auth.invalid_token",
        path=_routed_path(request),
        method=request.method,
        reason=exc.reason,
        # `detail` may carry IdP-controlled values; logs are operator-
        # only, so it stays here for forensic context.
        detail=exc.detail,
    )
    # Use ONLY the reason short-code for the response body + challenge.
    # Per RFC 6750 §3.1 error_description is optional; we still emit
    # it (carrying the same reason) for clients that grep for it, but
    # never include any caller-controlled or IdP-controlled value.
    challenge = _bearer_challenge(error=exc.reason, error_description=exc.reason)
    return JSONResponse(
        status_code=status.HTTP_401_UNAUTHORIZED,
        content={"detail": exc.reason},
        headers={"WWW-Authenticate": challenge},
    )


async def _handle_introspection_unavailable(request: Request, exc: Exception) -> JSONResponse:
    """Map `IntrospectionUnavailableError` to HTTP 503 + Retry-After.

    the issuer URL stays in the structured log
    line only; the response body emits a generic message. Echoing
    the specific issuer back to an unauthenticated caller lets an
    attacker map which upstream IdP is degraded -- useful for
    timing credential-stuffing runs against the IdP itself.
    """
    assert isinstance(exc, IntrospectionUnavailableError)
    _log.warning(
        "auth.introspection_unavailable",
        path=_routed_path(request),
        method=request.method,
        # Issuer + detail stay in logs only (operator forensics).
        issuer=exc.issuer,
        detail=exc.detail,
    )
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={
            "detail": ("Token introspection upstream is currently unavailable. Retry shortly.")
        },
        # `Retry-After: 5` is RFC 7231 §7.1.3 in delta-seconds form.
        # Five seconds is short enough to feel responsive once the IdP
        # is back, long enough that retries don't hammer the verifier.
        headers={"Retry-After": "5"},
    )


def register_auth_exception_handlers(app: FastAPI) -> None:
    """Register the auth-layer exception handlers on `app`.

    Idempotent in practice (FastAPI overrides on re-register). Called
    once at app construction in `keeper.api.main.create_app`.

    Why this STILL exists when BearerAuthMiddleware calls the handlers
    inline: routes / Depends that raise these errors AFTER middleware
    runs (for example a future BC handler that re-verifies a token at a
    sensitive boundary) need the standard exception-handler chain.
    Belt-and-suspenders: the middleware handles the bearer-path
    raises directly (BaseHTTPMiddleware quirk), and the registered
    handlers catch any other raise site.
    """
    handler_invalid: Any = _handle_invalid_token
    handler_unavailable: Any = _handle_introspection_unavailable
    app.add_exception_handler(InvalidTokenError, handler_invalid)
    app.add_exception_handler(IntrospectionUnavailableError, handler_unavailable)


# Public aliases for direct invocation by the middleware (which has
# to call them inline to work around BaseHTTPMiddleware's
# exception-routing quirk; see the middleware module docstring).
handle_invalid_token = _handle_invalid_token
handle_introspection_unavailable = _handle_introspection_unavailable


__all__ = [
    "handle_introspection_unavailable",
    "handle_invalid_token",
    "missing_bearer_challenge",
    "register_auth_exception_handlers",
]
