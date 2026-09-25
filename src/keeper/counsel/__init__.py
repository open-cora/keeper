"""Counsel: what was put forward to run next, and was it taken.

One aggregate, the Proposal, and three operations on it. A proposal is a
run an actor put forward, before anything has run it: which plan, with
what values, who advised it, and the run that took it if one has. An
actor is whoever authenticated, so a person and a piece of software make
the same record and nothing on it says which.

## Why the record is here and not on a Run

A proposal looks like a run that has not started, and modelling it as
one would save a context. A run's genesis requires an external
reference and a proposal has none; a pre-start status would add a second
claim to what Running means; and a proposal nothing came of would be a
run that never ran, sitting in every count of how many runs there were.

## The join this context adds

Custody holds the join from a run to the data it produced. This one
holds the join back, from an actor's advice to the run that took it.
Neither join is held by any engine or store, and together they are the
loop.

Nothing writes that join automatically. The reporter has never heard of
a proposal, and Execution knows nothing of this context and is not told,
so the agent that proposed is the one that closes it: it submits with a
reference of its own choosing, resolves that reference through the run
listing, and records the result here.

## What it reaches across for

Execution, in one direction, and nothing reaches back. Making a
proposal loads a plan, because the decision checks the proposed values
against the schema the plan declares. Taking one loads a run, because
the decision compares the plan the run actually ran against the plan
that was proposed.

## Where the tree stands on time

`make_proposal` accepts no `occurred_at` and `take_proposal` does, which
is R8 running between two commands on one stream rather than between
contexts. Proposing is a speech act, so the call is the act and this
system is the authority for the fact. A run started in an engine at a
moment nothing here was present for.
"""

from keeper.counsel.aggregates.proposal import Proposal, load_proposal
from keeper.counsel.errors import UnauthorizedError
from keeper.counsel.projections import register_counsel_projections
from keeper.counsel.routes import register_counsel_routes
from keeper.counsel.tools import register_counsel_tools
from keeper.counsel.wire import CounselHandlers, wire_counsel

__all__ = [
    "CounselHandlers",
    "Proposal",
    "UnauthorizedError",
    "load_proposal",
    "register_counsel_projections",
    "register_counsel_routes",
    "register_counsel_tools",
    "wire_counsel",
]
