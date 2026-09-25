"""Reusable machinery a bounded context's slices are built from.

A slice is one feature: a command handler, its route, its MCP tool. Each
module here was extracted after the same code had been written out per
aggregate enough times to be worth naming, and each is consumed by slices
rather than by the composition root.

  - `evolver`     folding an event stream back into current state
  - `envelope`    wrapping a domain event for storage
  - `payload`     unwrapping one, with uniform error handling
  - `idempotency` making a retried command safe to repeat
  - `principal`   caller identity inside an MCP tool

Every module here has a caller, which was not true when the list was
longer. Two entries are gone: the single-stream update handler and the
keyset-paginated query handler, both shipped ahead of a consumer and
deleted once two bounded contexts had landed without wanting either.
Three helpers inside `payload` are still uncalled, which is a smaller
question than a module was and is answered the same way, by the next
aggregate that needs one or does not.

The split from the rest of `infrastructure/` is by reader: the modules at
the package root describe how the application is assembled and are read
once each, while these are read every time a slice is written.
"""
