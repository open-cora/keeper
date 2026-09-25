"""Edge-auth plumbing package.

Holds the auth-edge pieces that are NOT `TokenVerifier` port adapters:

  - `BearerAuthMiddleware` (Starlette middleware), verifies inbound
    `Authorization: Bearer` tokens via the kernel's configured verifier.
  - `IdpRegistry`: process-singleton router that picks the
    right `TokenVerifier` adapter per token's issuer.
  - `IdpConfig` + `IdpSubjectBinding` + `StaticSubjectMapper`:
    config and subject-mapping helpers.
  - `build_idp_registry`, `build_static_subject_mapper`: composition-root
    factories.
  - `exception_handlers.py`: FastAPI exception handler functions that
    convert auth errors into RFC 6750 401 / RFC 7231 503 responses.

The `TokenVerifier` port adapters themselves live at
`keeper.infrastructure.adapters.jwt_token_verifier::JwtTokenVerifier` and
`keeper.infrastructure.adapters.introspection_token_verifier::IntrospectionTokenVerifier`
per the locked `<Tech><Port>` naming rule.

Library over DIY: PyJWT is the
one library dependency; everything else is hand-written.
"""

from keeper.infrastructure.auth.build_registry import build_idp_registry
from keeper.infrastructure.auth.config import (
    IdpConfig,
    IdpSubjectBinding,
    StaticSubjectMapper,
    build_static_subject_mapper,
)
from keeper.infrastructure.auth.registry import IdpRegistry

# NB: `BearerAuthMiddleware` (auth/bearer.py) is intentionally NOT
# re-exported from this package init. Re-exporting it would import
# auth.bearer at auth-package load time, which triggers a cycle:
# Settings -> auth.config -> auth.__init__ -> auth.bearer -> request
# (mid-load, on the path that started this whole chain via
# observability -> Settings). main.py imports
# `from keeper.infrastructure.auth.bearer import
# BearerAuthMiddleware` directly to side-step the package init.
__all__ = [
    "IdpConfig",
    "IdpRegistry",
    "IdpSubjectBinding",
    "StaticSubjectMapper",
    "build_idp_registry",
    "build_static_subject_mapper",
]
