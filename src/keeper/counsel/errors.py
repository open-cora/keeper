"""Application-layer errors for the Counsel bounded context.

Distinct from the domain errors in the aggregate, which say a rule was
broken. These say the caller was not allowed to ask, which is not a fact
about a proposal at all.

A fifth class with the same name and the same body now exists, one per
context. Execution's copy said the next context to need one is the
trigger to hoist, on the rule of three; Custody's said the same and
declined for the same reason, that moving it touches every handler in
the tree and a landing that adds a context should not also reshape the
ones beside it. That reasoning holds here and is now two contexts old,
which is worth naming rather than repeating: the move is overdue and it
is its own commit.
"""


class UnauthorizedError(Exception):
    """The calling principal may not issue this command.

    Raised by a handler after the authorization port denies, carrying the
    reason the port gave. Surfaces as 403 over HTTP and as an error result
    over MCP.
    """


__all__ = ["UnauthorizedError"]
