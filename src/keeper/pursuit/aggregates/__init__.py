"""Aggregates of the Pursuit bounded context.

One aggregate, the Pursuit. This package is also the read-side surface a
sibling context would reach into, which is why the cross-BC doors in
`tach.toml` name `keeper.<bc>.aggregates` rather than a bare package. No
sibling reaches in here, and none should: a pursuit is what authorized
work rather than anything the work produced, so a context asking about one
would be asking why something ran rather than what it did.

This context reaches into none of them either, yet. Authorizing a loop and
revoking one are both decisions about this aggregate alone, and neither
needs to know what is running. The doors will run outward when a verb here
acts on a record Counsel or Execution holds, and this is the direction they
will run: never back.
"""
