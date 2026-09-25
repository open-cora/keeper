"""Aggregate kernels for the Execution bounded context.

The half of this context a sibling may read. A bounded context that needs
a fact about a plan reaches under `aggregates`; it never reaches into
`features`, which holds the slice handlers.

No sibling reads it yet, so there is no `[[interfaces]]` block in
tach.toml narrowing the door the way Access has one. Such a block is
written off what a consumer actually imports, which is the only honest
way to size a public surface, so it waits for the consumer.
"""
