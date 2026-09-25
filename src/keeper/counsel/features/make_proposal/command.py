"""The intent: put a run forward, before anything has run it."""

from dataclasses import dataclass
from typing import Any
from uuid import UUID


@dataclass(frozen=True)
class MakeProposal:
    """Put forward a run of this plan, with these values.

    Make, not define and not register. Neither of the glossary's two
    genesis words fits: that pair was built for things that persist as
    specifications, and a proposal is an act. "Make a proposal" is the
    phrase people say, which is what R1 in docs/reference/naming.md asks
    of a name.

    **There is no `occurred_at`, and the absence is the point.** Every
    other command in this tree that records an act takes one, because
    the act happened elsewhere and the report is late.
    Proposing is a speech act: the call IS the proposing, so there is no
    earlier moment for the record to be late to, and the moment this
    system writes one is the moment it happened. That is R8 landing on
    the makes side, beside `register_actor` and `define_plan` rather
    than beside `register_dataset`.

    A proposer that decided elsewhere and tells this system afterwards is
    a different command when it arrives, with its own genesis event and
    its own timestamp. Two event classes rather than a flag on one.

    **There is no proposer either.** The handler writes the
    authenticated principal, so a caller controls who it proposed as
    exactly as much as a caller of `register_actor` controls the new
    actor's id. A caller naming its own proposer could advise as
    somebody else.

    The proposal id and the correlation id are not the caller's. They
    come from the handler's ports, so the decision this command produces
    is reproducible on replay.
    """

    plan_id: UUID
    parameters: dict[str, Any]


__all__ = ["MakeProposal"]
