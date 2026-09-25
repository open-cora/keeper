"""Wire `Settings.identity_providers` → `IdpRegistry`.

Composition-root factory. Called once at lifespan start; the
resulting registry is held on the Kernel and injected into the
FastAPI/MCP middleware. Tests build the registry directly from
`IdpConfig` instances via the helper to skip the
Settings layer.

## Why a factory module

Each `IdpConfig` entry could produce a JwtTokenVerifier
adapter, an IntrospectionTokenVerifier adapter, or both, depending on
which URLs the operator supplied. The registry takes the constructed
adapter instances; this module owns the "config row → adapter
instance(s)" translation so the registry stays a thin router.

Name matches the codebase composition-root convention
(the per-BC `build_*` modules): one-shot
`build_<port>(...)` constructors at the composition boundary.
`Builder` in DDD vocabulary implies an incremental/fluent shape;
this is a one-shot
`build_idp_registry(configs) -> IdpRegistry` which is
the Factory shape.

## Subject mapper

The factory takes a single SubjectMapper that all constructed
verifiers share (one BC owns the IdP-subject to principal-id
mapping table across all IdPs). Default is `StaticSubjectMapper`;
the projection-backed mapper is the alternative.
"""

from keeper.infrastructure.adapters.introspection_token_verifier import IntrospectionTokenVerifier
from keeper.infrastructure.adapters.jwt_token_verifier import JwtTokenVerifier
from keeper.infrastructure.auth.config import IdpConfig
from keeper.infrastructure.auth.registry import IdpRegistry
from keeper.infrastructure.ports.token_verifier import SubjectMapper


def build_idp_registry(
    identity_providers: list[IdpConfig],
    *,
    subject_mapper: SubjectMapper,
) -> IdpRegistry | None:
    """Construct an `IdpRegistry` from configured providers.

    Returns None when `identity_providers` is empty, callers (the
    lifespan code) treat None as "edge-auth disabled, fall through
    to the legacy X-Principal-Id path." This matches the existing
    `trust_policy_id: UUID | None = None` shape where None disables
    a real authorize adapter in favour of `AllowAllAuthorize`.

    Per the registry contract: at least ONE adapter must be
    constructed across all providers, or the registry constructor
    raises. An IdP entry can produce both a JwtTokenVerifier AND an
    IntrospectionTokenVerifier if both URLs are configured (uncommon but
    legitimate for IdPs that issue JWTs by default but need
    introspection for revocation-sensitive callers).

    Only ONE IntrospectionTokenVerifier total is supported today (one per
    deployment). A configuration with two
    introspection-providing IdPs raises ValueError: the registry's
    opaque-token routing can't disambiguate. JWT IdPs route by `iss`
    so any number is fine.
    """
    if not identity_providers:
        return None

    jwt_verifiers: list[JwtTokenVerifier] = []
    introspection_token_verifier: IntrospectionTokenVerifier | None = None

    for config in identity_providers:
        if config.jwks_url is not None:
            jwt_verifiers.append(
                JwtTokenVerifier(
                    issuer=config.issuer,
                    jwks_url=config.jwks_url,
                    audience_for_surface=config.audiences,
                    subject_mapper=subject_mapper,
                    allowed_algorithms=config.allowed_algorithms,
                    principal_kind=config.principal_kind,
                    allow_insecure_jwks_url=config.allow_insecure_jwks_url,
                )
            )
        if config.introspection_url is not None:
            if introspection_token_verifier is not None:
                msg = (
                    f"build_idp_registry: more than one IdpConfig "
                    f"declares introspection_url (one for {introspection_token_verifier.issuer!r}, "
                    f"another for {config.issuer!r}). The registry's opaque-token "
                    "routing supports exactly one IntrospectionTokenVerifier per "
                    "deployment today. If the deployment needs multi-IdP "
                    "introspection, the registry's opaque routing needs a "
                    "discriminator extension (token prefix per GitHub PAT "
                    "pattern) before this is removed."
                )
                raise ValueError(msg)
            # narrow contract: introspection creds + url presence
            # validated by IdpConfig._introspection_creds_pair.
            # Explicit raise (not `assert`) so a future refactor that
            # breaks the validator doesn't silently UB under `python -O`.
            if config.introspection_client_id is None or config.introspection_client_secret is None:
                msg = (
                    f"build_idp_registry invariant violated: IdP {config.issuer!r} "
                    "has introspection_url but missing creds; "
                    "IdpConfig._introspection_creds_pair should have caught this."
                )
                raise RuntimeError(msg)
            introspection_token_verifier = IntrospectionTokenVerifier(
                issuer=config.issuer,
                introspection_url=config.introspection_url,
                client_id=config.introspection_client_id,
                client_secret=config.introspection_client_secret,
                audience_for_surface=config.audiences,
                subject_mapper=subject_mapper,
                cache_ttl_seconds=config.introspection_cache_ttl_seconds,
                principal_kind=config.principal_kind,
                allow_insecure_introspection_url=config.allow_insecure_introspection_url,
            )

    return IdpRegistry(
        jwt_verifiers=jwt_verifiers,
        introspection_token_verifier=introspection_token_verifier,
    )


__all__ = ["build_idp_registry"]
