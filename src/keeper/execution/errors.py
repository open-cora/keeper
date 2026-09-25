"""Application-layer errors for the Execution bounded context.

Distinct from the domain errors in the aggregate, which say a rule was
broken. These say the caller was not allowed to ask, which is not a fact
about a plan at all.

A third class with the same name and the same body now exists in each of
the three contexts. That is the rule of three, so the next context to
need one is the trigger to hoist rather than to copy: three identical
copies is where a shared form stops being a guess. It is not hoisted in
this commit because moving it touches every handler in the tree, and a
landing that adds a context should not also be the one that reshapes the
other two.
"""


class UnauthorizedError(Exception):
    """The calling principal may not issue this command.

    Raised by a handler after the authorization port denies, carrying the
    reason the port gave. Surfaces as 403 over HTTP and as an error result
    over MCP.
    """


__all__ = ["UnauthorizedError"]
