"""Aggregate kernels for the Access bounded context.

The half of this context a sibling may read. A bounded context that
needs a fact about an actor reaches under `aggregates`; it never reaches
into `features`, which holds the slice handlers. That much tach enforces
today, as a declared edge on `keeper.access.aggregates`.

How wide the door is is now settled, and it is one name. Authority
reads `load_actor` and nothing else, so tach.toml carries an
`[[interfaces]]` block scoped to that context with exactly that entry.
Access's own slices still see the whole package, which they need: a
decider, its events and its fold all live under here.

The set was read off what the consumer imports rather than guessed at
before one existed, which is the only honest way to size a public
surface, and `tests/architecture/test_tach_edges_are_used.py` keeps it
that way by failing on an exposed name nobody takes up.

What the block keeps out is the point of it. `from_stored`, `fold` and
the event classes are exported because Access's own slices need them
across modules, not because a sibling should have them, and a sibling
holding those could build an actor event and append it, going around the
deciders instead of through them.
"""
