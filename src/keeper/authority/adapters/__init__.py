"""Adapters this bounded context supplies to ports declared elsewhere.

One today: `PolicyAuthorize`, the real implementation of the `Authorize`
port in `keeper.infrastructure.ports`. The port is declared in
infrastructure because every bounded context calls it; the
implementation lives here because Authority is the context that owns
what a policy means.

That split is what keeps the composition root free of bounded-context
imports. `build_kernel` never names this package: `api/main.py` passes
`build_authorize` in as a factory, and `build_kernel` receives a thing
satisfying a Protocol it already knows.
"""

from keeper.authority.adapters.policy_authorize import PolicyAuthorize, build_authorize

__all__ = ["PolicyAuthorize", "build_authorize"]
