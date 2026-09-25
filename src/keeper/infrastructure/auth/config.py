"""Settings-loadable schema for edge-auth identity providers.

Defines the typed shape that `Settings.identity_providers` carries
(loaded from env vars in `keeper.infrastructure.settings.Settings`).
Production deployments configure one entry per IdP that mints tokens
for the keeper: an introspection-only provider such as Globus Auth, a JWT
provider such as Microsoft Entra,
etc.

Also defines `StaticSubjectMapper`, a SubjectMapper that holds a
fixed `(issuer, subject) → (principal_id, kind)` dict, sufficient
for small deployments (roughly ten humans plus one or two service
accounts). A projection-backed mapper
is the alternative for larger deployments that mint Actors at
runtime.

## Why two mappers (precedent)

Borrowed rather than invented: a data server in the same
scientific-facility ecosystem faces the same problem and splits it the
same way, with a static dict for small and test deployments and an
OIDC-projection-backed mapper for large ones. Both satisfy
`keeper.infrastructure.ports.token_verifier.SubjectMapper`, so the
registry doesn't know or care which is wired.

The precedent used to be cited by name here. It is not any more, and
the edit is worth a line because the sentence did not change meaning:
what carries the argument is that somebody solving this problem at this
scale reached for two mappers, not which product they were building.
Naming it stopped being a neutral citation once a bounded context in
this tree started recording which store holds what. See
`tests/architecture/test_the_domain_names_no_product.py`.
"""

from collections.abc import Mapping
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, SecretStr, model_validator

# Local Literal alias to avoid a top-level import from
# `keeper.infrastructure.ports.token_verifier`. That import would
# trigger a cycle: Settings (keeper.infrastructure.settings) needs this
# IdpConfig, and ports.token_verifier transitively
# imports through observability back to Settings. The values MUST
# stay in sync with `PrincipalKind` on the port; the static
# `StaticSubjectMapper` below imports the port lazily inside its
# method (signature uses the local alias too). NOTHING PINS THE DRIFT:
# these two literals and the port's `PrincipalKind` are maintained by
# hand, and a fitness test cross-checking them is worth adding the
# first time either side gains a member.
_PrincipalKindLiteral = Literal["human", "service_account"]


class IdpSubjectBinding(BaseModel):
    """Single `(subject) -> (actor_id, kind?)` row for a single IdP.

    Carried on `IdpConfig.subject_bindings`. The
    composition root merges all bindings across all IdPs into a
    single `StaticSubjectMapper` keyed on `(issuer, subject)`; the
    issuer comes from the enclosing IdP config so it's not repeated
    here.

    `kind` is optional: when `None` (default), the merge step
    inherits the enclosing IdP's `principal_kind`. Set explicitly
    only to override that default for an individual subject; useful
    when an IdP serves both humans and service accounts and a few
    bindings need to disagree with the IdP-wide default.

    Defined ABOVE `IdpConfig` deliberately so the
    `subject_bindings` field annotation is a direct class reference
    instead of a Pydantic forward-ref string; a typo or rename then
    fails at module import rather than at first-validation time.
    """

    subject: str = Field(
        ...,
        description=(
            "Raw `sub` claim string from the IdP, exact match. For "
            "OIDC humans this is typically the IdP's stable user id "
            "(for example an Entra GUID); for client_credentials service "
            "accounts it's the OAuth client id."
        ),
    )
    actor_id: UUID = Field(
        ...,
        description="The principal UUID this subject maps to.",
    )
    kind: _PrincipalKindLiteral | None = Field(
        default=None,
        description=(
            "Discriminates human vs service-account. When `None` "
            "(default), the binding inherits the enclosing IdP's "
            "`principal_kind`. Set explicitly only to override that "
            "default for an individual subject."
        ),
    )


class IdpConfig(BaseModel):
    """Per-IdP configuration loaded from `Settings.identity_providers`.

    Each entry binds a single OIDC issuer URL to either a JWT path
    (jwks_url required) or an introspection path (introspection_url
    + introspection_client_id + introspection_client_secret required),
    or both (introspection used for revocation-sensitive callers).

    The `audiences` map binds the 3 SYSTEM Surface UUIDs to the
    audience strings the IdP signs into the token's `aud` claim for
    that Surface. The keeper registers itself with the IdP using these
    audience strings; the IdP issues tokens with `aud=<the one for
    the Surface the caller wants to reach>`.

    `allow_insecure_*_url` opt-ins exist for test/dev fixtures that
    use localhost endpoints; production deployments leave these
    False so the constructor rejects http:// URLs.
    """

    issuer: str = Field(
        ...,
        description=(
            "OIDC issuer URL, exact match against the 'iss' claim on "
            "every token. Must match the IdP's published metadata; "
            "trailing-slash lenient matching is NOT performed (matches "
            "RFC 9068 §4 expectation that iss is exact-match)."
        ),
    )

    jwks_url: str | None = Field(
        default=None,
        description=(
            "JWKS endpoint URL. Required when the IdP issues JWT access "
            "tokens (Microsoft Entra, Google, Auth0, Okta, AWS Cognito, "
            "Helmholtz AAI). Leave None for introspection-only IdPs "
            "(Globus Auth default)."
        ),
    )

    introspection_url: str | None = Field(
        default=None,
        description=(
            "RFC 7662 introspection endpoint URL. Required for IdPs that "
            "issue opaque tokens (Globus Auth) or when revocation must "
            "be checked per-request. Triggers the IntrospectionTokenVerifier "
            "adapter path."
        ),
    )

    introspection_client_id: str | None = Field(
        default=None,
        description=(
            "OAuth client id the keeper presents to the IdP's introspection "
            "endpoint via HTTP Basic. Required when introspection_url "
            "is set. Distinct from the user-facing client_id."
        ),
    )

    introspection_client_secret: SecretStr | None = Field(
        default=None,
        description=(
            "OAuth client secret paired with introspection_client_id. "
            "Required when introspection_url is set. SecretStr keeps it "
            "out of logs / __repr__ / model_dump_json."
        ),
    )

    audiences: dict[UUID, str] = Field(
        default_factory=lambda: {},
        description=(
            "Surface UUID → audience string. The keeper registers the audience "
            "strings with the IdP at deployment; the IdP signs them into "
            "the 'aud' claim. Per RFC 8707 §3 each Surface gets a "
            "distinct audience so cross-Surface token replay fails."
        ),
    )

    allowed_algorithms: list[str] = Field(
        default_factory=lambda: ["RS256", "ES256"],
        description=(
            "JWT signature algorithms accepted by the JwtTokenVerifier. "
            "Default ['RS256', 'ES256'] covers every mature OIDC IdP. "
            "The constructor rejects 'none' in any case (no-alg-none invariant)."
        ),
    )

    principal_kind: _PrincipalKindLiteral = Field(
        default="human",
        description=(
            "IdP-wide default kind. Applied to any "
            "`IdpSubjectBinding` whose own `kind` is unset (the "
            "common case). Set to `service_account` for IdPs that "
            "issue only client-credentials tokens (for example a CI-only "
            "IdP) so individual bindings can stay terse."
        ),
    )

    introspection_cache_ttl_seconds: int = Field(
        default=30,
        ge=1,
        description=(
            "Per-token introspection cache lifetime. Lower for stronger "
            "revocation, higher for less IdP load. "
            "Zero is forbidden (no introspection without a per-token cache)."
        ),
    )

    allow_insecure_jwks_url: bool = Field(
        default=False,
        description=(
            "Production MUST be False. Test/dev fixtures using "
            "http://127.0.0.1:... opt in; otherwise constructor "
            "rejects http://."
        ),
    )

    allow_insecure_introspection_url: bool = Field(
        default=False,
        description=(
            "Production MUST be False. Same shape as "
            "allow_insecure_jwks_url; without HTTPS the introspection "
            "POST leaks the keeper's client_secret to MITM."
        ),
    )

    subject_bindings: list[IdpSubjectBinding] = Field(
        default_factory=lambda: [],
        description=(
            "Static `(subject) -> Actor` map for this IdP. The "
            "composition root merges these across all IdPs into a "
            "single `StaticSubjectMapper` keyed on `(issuer, subject)`. "
            "Empty (default) is valid for IdPs that ship before any "
            "Actor is mapped: every bearer token from this IdP then "
            "fails with `unknown_subject` until an operator adds "
            "bindings. A future projection-backed mapper will replace "
            "this for deployments that mint Actors at runtime; the "
            "static field is the small-fixed-roster path."
        ),
    )

    @model_validator(mode="after")
    def _at_least_one_verification_path(self) -> "IdpConfig":
        """An IdP entry must provide at least one verification path
        (JWT, introspection, or both). An entry with neither would
        never authenticate any token from this issuer."""
        if self.jwks_url is None and self.introspection_url is None:
            msg = (
                f"IdpConfig for issuer={self.issuer!r} "
                "must specify jwks_url (JWT path) OR introspection_url "
                "(opaque path), or both. An entry with neither cannot "
                "authenticate any token."
            )
            raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def _introspection_creds_pair(self) -> "IdpConfig":
        """introspection_url requires both client_id and client_secret."""
        if self.introspection_url is not None and (
            self.introspection_client_id is None or self.introspection_client_secret is None
        ):
            msg = (
                f"IdpConfig for issuer={self.issuer!r}: "
                "introspection_url requires both introspection_client_id "
                "and introspection_client_secret (RFC 7662 §2.1 HTTP "
                "Basic auth)."
            )
            raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def _audiences_non_empty(self) -> "IdpConfig":
        """Audiences map MUST have at least one entry.

        An IdP entry with `audiences={}` validates structurally but
        produces a verifier that rejects every request with
        `wrong_audience`: a fail-late mode that violates the
        module-docstring promise of fail-fast startup validation.
        Operators get a 401 with no clue why; this validator names
        the missing config explicitly.
        """
        if not self.audiences:
            msg = (
                f"IdpConfig for issuer={self.issuer!r}: "
                "audiences map must have at least one Surface UUID → "
                "audience-string entry. An empty map produces a verifier "
                "that rejects every request with wrong_audience. Map at "
                "least one of the SYSTEM Surface UUIDs (HTTP=...0020, "
                "MCP_STDIO=...0021, MCP_STREAMABLE_HTTP=...0022) to the "
                "audience string the IdP signs into the 'aud' claim."
            )
            raise ValueError(msg)
        return self


class StaticSubjectMapper:
    """SubjectMapper backed by an in-memory `(issuer, subject) → (id, kind)` dict.

    Sufficient for small deployments (roughly ten
    humans + 1-2 service accounts) where the Actor set is fixed at
    deployment time and rarely changes.

    A projection-backed mapper is the sibling that queries an
    access-projection table for deployments with dynamic Actor
    registration. Both satisfy the SubjectMapper protocol; the
    registry doesn't care.

    An unmapped `(iss, sub)`
    not in the map raises `InvalidTokenError("unknown_subject", ...)`.
    The verifier's `safe_map_subject` helper would wrap a raw
    exception, but we raise the typed error directly so the route
    layer sees a clean 401 with the right reason code.
    """

    def __init__(
        self,
        bindings: Mapping[tuple[str, str], tuple[UUID, _PrincipalKindLiteral]],
    ) -> None:
        """Construct with a fixed binding mapping.

        Keys: `(issuer, subject)` tuple. Both strings exact-match.
        Values: `(principal_id, kind)` tuple.

        Accepts any `Mapping` for the immutable-interface convention
        used elsewhere in the tree. The mapping is defensive-copied
        into an internal dict at construction so callers can't mutate
        live auth behavior between requests.

        Usage:
            mapper = StaticSubjectMapper({
                ("https://idp.example.com", "user-abc"): (UUID(...), "human"),
                ("https://idp.example.com", "ci-bot"): (UUID(...), "service_account"),
            })
        """
        self._bindings: dict[tuple[str, str], tuple[UUID, _PrincipalKindLiteral]] = dict(bindings)

    async def __call__(self, issuer: str, subject: str) -> tuple[UUID, _PrincipalKindLiteral]:
        # Lazy import to avoid the Settings ↔ auth.config cycle (see
        # `_PrincipalKindLiteral` docstring above).
        from keeper.infrastructure.ports.token_verifier import InvalidTokenError

        mapping = self._bindings.get((issuer, subject))
        if mapping is None:
            raise InvalidTokenError(
                "unknown_subject",
                f"no Actor mapped for issuer={issuer!r} subject={subject!r}",
            )
        return mapping


def build_static_subject_mapper(
    identity_providers: list[IdpConfig],
) -> StaticSubjectMapper:
    """Merge `subject_bindings` across all IdPs into one `StaticSubjectMapper`.

    Called by `build_kernel` to construct the production subject
    mapper. Each `IdpSubjectBinding` from each IdP's
    `subject_bindings` list becomes one entry in the resulting map,
    keyed on `(idp.issuer, binding.subject)`.

    A binding with `kind=None` (the common case) inherits the
    enclosing IdP's `principal_kind` at merge time. A binding with
    `kind` set explicitly wins over the IdP default for that
    subject. Resolution happens here rather than in the verifier's
    `kind or self._principal_kind` fallback because the static
    mapper always returns a truthy kind, so that fallback never
    fires for this path, the inheritance MUST be applied here or
    the IdP-level default would be dead.

    Duplicate `(issuer, subject)` pairs across the configured IdPs
    raise `ValueError` at construction time, silent overwrite would
    let an operator's typo grant one IdP's `sub` to a different
    Actor's id without warning.
    """
    bindings: dict[tuple[str, str], tuple[UUID, _PrincipalKindLiteral]] = {}
    for idp in identity_providers:
        for binding in idp.subject_bindings:
            key = (idp.issuer, binding.subject)
            if key in bindings:
                msg = (
                    f"Duplicate IdP subject binding for issuer={idp.issuer!r} "
                    f"subject={binding.subject!r}. Each `(issuer, subject)` "
                    "pair must map to exactly one Actor; remove the duplicate "
                    "from identity_providers config."
                )
                raise ValueError(msg)
            resolved_kind: _PrincipalKindLiteral = (
                binding.kind if binding.kind is not None else idp.principal_kind
            )
            bindings[key] = (binding.actor_id, resolved_kind)
    return StaticSubjectMapper(bindings)


__all__ = [
    "IdpConfig",
    "IdpSubjectBinding",
    "StaticSubjectMapper",
    "build_static_subject_mapper",
]
