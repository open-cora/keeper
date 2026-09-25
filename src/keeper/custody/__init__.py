"""Custody bounded context.

Owns where the data a run produced is being kept, and who is keeping it.
One aggregate:

    dataset   one body of data a run produced: which run made it, and
              what the store holding it calls it.

## What it is not

Not the data, and not a copy of anything about the data. The store holds
the bytes, their shape and their metadata, and it is addressable. What no
store holds is which run produced what it is keeping, because a store was
handed an engine's own identifier and this system is the only place that
identifier has been resolved to a run. The join is the whole of what this
context adds, and every field that is not the join was left out on
purpose.

Not provenance either, although that is the word most people reach for.
Provenance is the whole causal graph, and two thirds of it are already
elsewhere in this tree: the agent is an actor in Access and the activity
is a run in Execution. A context holding the third part and named after
the whole would claim more than it carries. Custody says what this one
can back: where the thing is, and on whose word.

## Who drove the act

Reported, permanently, and unlike Execution there is no second mode
waiting. Even a deployment where this system conducted the run would not
have written the data: some writer did, and this context would still be
hearing about it afterwards. So the genesis command is `register_dataset`
and no prefixed sibling is coming to sit beside it.

Registered rather than defined, because the data exists in the store
whether or not anything here has heard of it and the record enrols it.
That makes it the first `register_*` in this tree that describes a fact
rather than making one, which is why it accepts a timestamp its caller
supplies where `register_actor` does not.

## What it reaches across for

Execution, in one direction, for two names, both serving one check: the
registering handler loads a run so it can refuse a dataset citing one
that does not exist. Nothing in Execution reaches back.

The timestamp helper the registering command calls used to come through
that door too. It lives in `keeper.shared.instant` now, because a third
consumer arrived and met the rule of three.
"""

from keeper.custody.aggregates.dataset import Dataset, load_dataset
from keeper.custody.errors import UnauthorizedError
from keeper.custody.projections import register_custody_projections
from keeper.custody.routes import register_custody_routes
from keeper.custody.tools import register_custody_tools
from keeper.custody.wire import CustodyHandlers, wire_custody

__all__ = [
    "CustodyHandlers",
    "Dataset",
    "UnauthorizedError",
    "load_dataset",
    "register_custody_projections",
    "register_custody_routes",
    "register_custody_tools",
    "wire_custody",
]
