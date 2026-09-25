"""Application-layer errors for the Equipment bounded context.

Distinct from the domain errors in the aggregate, which say a rule was
broken. These say the caller was not allowed to ask, which is not a fact
about a device at all.

A sixth class with the same name and the same body now exists, one per
context. Execution's copy said the next context to need one is the
trigger to hoist, on the rule of three; Custody's and Counsel's each
said the same and declined, that moving it touches every handler in the
tree and a landing that adds a context should not also reshape the ones
beside it. That reasoning is now three contexts old and has stopped
being a reason. The move is overdue, it is its own commit, and this copy
exists so that commit can delete six things at once rather than five.
"""


class UnauthorizedError(Exception):
    """The calling principal may not issue this command.

    Raised by a handler after the authorization port denies, carrying the
    reason the port gave. Surfaces as 403 over HTTP and as an error result
    over MCP.
    """


__all__ = ["UnauthorizedError"]
