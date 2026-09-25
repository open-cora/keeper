"""The intent: hand a procedure out to be driven."""

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class DispatchExecution:
    """Dispatch this procedure, so that something can take it up and drive it.

    Dispatch, not report, and the word is the whole posture. An earlier
    shape had a driver tell this system that it had walked something,
    which made the record secondhand by construction. This system now
    asks, so the genesis says so, and which class opened a stream is what
    says who drove the act.

    One field. The procedure holds the steps, their order and the devices
    each one touches, so a caller that also supplied a step list would be
    able to dispatch something other than what it named.

    The execution id and the correlation id are not the caller's. They come
    from the handler's ports, so the decision this command produces is
    reproducible on replay.

    No `occurred_at`. A dispatch happens here, at the moment this system
    writes it, so there is no earlier instant for a caller to report.
    That is R8 in docs/reference/naming.md, and it is the line that
    separates this command from the step reports that follow it: those
    describe something that happened elsewhere and take one.
    """

    procedure_id: UUID


__all__ = ["DispatchExecution"]
