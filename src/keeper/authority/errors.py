"""Application-layer errors for the Authority bounded context.

Distinct from the domain errors in the aggregate, which say a rule was
broken. These say the caller was not allowed to ask, which is not a fact
about a policy at all.

Its own class rather than a shared one with Access. The two are matched
to status codes by `isinstance`, and a single hoisted class would make
every context's refusal indistinguishable at the point where a reader
most wants to know which context refused.
"""


class UnauthorizedError(Exception):
    """The calling principal may not issue this command.

    Raised by a handler after the authorization port denies, carrying
    the reason the port gave. Surfaces as 403 over HTTP and as an error
    result over MCP.
    """


__all__ = ["UnauthorizedError"]
