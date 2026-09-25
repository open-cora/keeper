"""Application-layer errors for the Access bounded context.

Distinct from the domain errors in the aggregate, which say a rule was
broken. These say the caller was not allowed to ask, which is not a fact
about an actor at all.
"""


class UnauthorizedError(Exception):
    """The calling principal may not issue this command.

    Raised by a handler after the authorization port denies, carrying the
    reason the port gave. Surfaces as 403 over HTTP and as an error result
    over MCP.
    """


__all__ = ["UnauthorizedError"]
