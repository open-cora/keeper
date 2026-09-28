"""The intent: revoke the authorization before it runs itself out."""

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class WithdrawPursuit:
    """Stop this pursuit authorizing anything further.

    One field, and nothing else could sensibly be on it. There is no
    reason string: a person stopping a loop at a beamline is doing it
    because they are standing there, and a free-text field on a record
    nobody can edit is where an account of a person ends up. Who withdrew
    it is on the record, and asking them is better than reading what they
    typed at the time.

    **There is no `occurred_at`.** Revoking is a speech act like
    authorizing, and it happens where it is spoken. R8, makes side, beside
    `start_pursuit`.

    This does not reach anything already dispatched. Work at a beamline
    keeps running and the executions this pursuit produced stay exactly as
    they are. What ends is the permission to produce more.
    """

    pursuit_id: UUID


__all__ = ["WithdrawPursuit"]
