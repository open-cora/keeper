"""The intent: take this advice, and commit the facility to it."""

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class AdoptProposal:
    """Adopt this proposal, at this beamline, over these devices.

    Adopt rather than enact, and rather than accept. Enacting names what
    happens elsewhere, which is a procedure composed and an execution
    dispatched, and this context is named for what it keeps rather than
    for what happens elsewhere. Accepting is reserved for a person
    approving something that may then never run, and spending it here
    would leave that command nothing to be called.

    **Three fields, and two of them are the caller's because nothing here
    can derive them.** A proposal cites a plan and carries values, which
    is not enough to compose a procedure out of: `define_procedure` says
    a beamline cannot be derived because the steps imply it in a prefix
    this system deliberately does not parse, and an acquisition
    declaring no devices is refused outright, because a step believed to
    touch nothing can run beside another over the same motor.

    So the bound is stated rather than inferred. A thinker or an
    operator reading the execution a proposal came from can see what
    that plan touched last time and offer those values, and offering is
    where that belongs: a bound the system guessed is one nobody
    decided.

    **There is no `occurred_at`.** Adopting is an act this system
    performs and the call is the performing, so there is no earlier
    moment for the record to be late to. That is R8 on the makes side,
    beside `make_proposal` rather than beside `take_proposal`.

    **There is no procedure name.** One proposal is one run of one plan,
    so the routine composed for it is named after the plan it runs, and
    a caller naming it would be naming something it did not compose.
    """

    proposal_id: UUID
    beamline: str
    scopes: tuple[str, ...]


__all__ = ["AdoptProposal"]
