"""The refusal every bounded context raises, in one place.

Six contexts each declared this class, and the six declarations were
byte for byte the same. That is the shape the rule of three exists for,
and it went to six because each landing that needed one found five
already there and copied the nearest.

## Why it is shared where a domain error would not be

A domain error says a rule of some aggregate was broken, and those stay
with their aggregates: `ProposalCannotBeAdoptedError` means something
only in Counsel, and a shared one would have to name an aggregate it
could not see.

This says the caller was not allowed to ask. That is not a fact about an
actor, a proposal or a device, and nothing about it differs by context:
the authorization port denied, the reason came back, and the answer is
403. There was never a Counsel version of it to tell apart from an
Access version.

## What the six copies cost beyond the duplication

One exception handler each. FastAPI keys handlers on the class, so six
classes meant six registrations of one mapping, in six `routes.py`
modules, each of which had to be kept in step with the others by hand.
One class needs one registration, and it belongs with the other
cross-cutting ones in `keeper.api.exception_handlers` rather than in
whichever context happened to be asked first.

## Why `shared` and not `infrastructure`

Every module may import `keeper.shared` without a dependency edge, which
is what lets all six contexts reach this without any of them depending
on another. `infrastructure` is the chassis a context is handed rather
than a vocabulary it shares, and this is a word rather than a mechanism.
"""


class UnauthorizedError(Exception):
    """The calling principal may not issue this command.

    Raised by a handler after the authorization port denies, carrying the
    reason the port gave. Surfaces as 403 over HTTP and as an error result
    over MCP.
    """


__all__ = ["UnauthorizedError"]
