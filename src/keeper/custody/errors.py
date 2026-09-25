"""Application-layer errors for the Custody bounded context.

Distinct from the domain errors in the aggregate, which say a rule was
broken. These say the caller was not allowed to ask, which is not a fact
about a dataset at all.

A fourth class with the same name and the same body now exists, one per
context. Execution's copy said the next context to need one is the
trigger to hoist, on the rule of three, and this is that context. It is
still not hoisted here, for the reason that note gave in advance: moving
it touches every handler in the tree, and a landing that adds a context
should not also be the one that reshapes the other three. The trigger has
fired and the move is its own commit.
"""


class UnauthorizedError(Exception):
    """The calling principal may not issue this command.

    Raised by a handler after the authorization port denies, carrying the
    reason the port gave. Surfaces as 403 over HTTP and as an error result
    over MCP.
    """


__all__ = ["UnauthorizedError"]
