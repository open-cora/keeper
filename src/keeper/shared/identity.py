"""Cross-BC identity NewType aliases for fact-act attribution.

A structural check can detect attribution fields by TYPE rather than by name:
a state field is an attribution field when its annotation is `ActorId`,
`ActorId | None`, `AgentId`, or `AgentId | None`. Bare `UUID` annotations are
skipped. That shifts the discipline from "exhaustively enumerate every
attribution field name" to "always use the right NewType at the annotation
site", which is what makes such detection robust.

Two aliases ship today:

  - `ActorId`: a UUID identifying a principal. Folded onto state by the
    `<verb>_by` attribution field whenever the act was performed by a
    principal.
  - `AgentId`: a UUID identifying an autonomous agent. An agent is also a
    principal, so the two are value-equal wherever an agent acts, but the
    typing distinction lets a slice that specifically wants an agent reject a
    bare principal at type-check time.

A non-principal trigger source (a monitor, a scheduler tick) gets its own
alias here when the first aggregate models one, alongside the discriminated
union its attribution field takes. Adding the alias before a carrier exists
would be a type nothing annotates.

NewType is preferred over `TypeAlias` because the wrapper is a true distinct
type at type-check time (pyright rejects `UUID -> ActorId` without an explicit
`ActorId(uuid)` call) while remaining a zero-cost identity function at runtime.
This gives a structural check a load-bearing signal with no runtime tax.
"""

from typing import NewType
from uuid import UUID

ActorId = NewType("ActorId", UUID)
AgentId = NewType("AgentId", UUID)


__all__ = [
    "ActorId",
    "AgentId",
]
