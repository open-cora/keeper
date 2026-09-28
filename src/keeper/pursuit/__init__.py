"""Pursuit: what a person authorized a machine to do, and how far it may go.

One aggregate, the Pursuit, and three operations on it. A pursuit is a
bounded, goal-oriented, autonomous loop: it observes an execution, asks
what should run next, dispatches the answer, and observes that in turn,
toward one goal within one beamline, one set of scopes and one budget,
until the objective is met or a stopping condition is reached.

## Why this context exists

Advice can already become work. A proposal names a plan and its values,
and adopting one composes a procedure and dispatches an execution in a
single transaction. What adopting cannot do is decide that it should
happen: two of the three facts a procedure needs beyond the proposal are
safety-bearing, and neither the beamline nor the scopes may be inferred
from anything. So a caller states them, every time, and the caller that
states them has to be a person.

That is the reason every step of the loop currently stops and waits for
somebody. A pursuit is where the person states them once, with a goal and
a limit attached, so that what follows is a statement already made being
applied rather than a machine working something out.

## Why it is not part of Counsel

Counsel is the record of advice, and its own glossary entry says it claims
the advice and never the weighing. A pursuit is not advice. It is
authorization, written by a person rather than an agent, lasting days
rather than a moment, and it reaches both Counsel and Execution where
Counsel reaches only Execution. Putting it there would make that sentence
false and would widen that context's door to carry this context's
coupling.

## What acts on a pursuit

Something outside, and nothing in here. No projection reacts, no
subscriber fires, and no command is issued by this system to itself. A
caller notices that an execution ended and calls in, the way the work
intake's caller notices that an execution was dispatched, and that caller
holds no authority at all.

It also needs no claim, unlike the conductor beside it. Two conductors
walking one procedure would move one motor twice, so a conductor claims.
Two callers driving one pursuit both append at the version they folded,
one wins, and the loser is refused by what it finds already written. The
record is what serializes them, which is why nothing in this context
leases, locks or elects.
"""

from keeper.pursuit.projections import register_pursuit_projections
from keeper.pursuit.routes import register_pursuit_routes
from keeper.pursuit.tools import register_pursuit_tools
from keeper.pursuit.wire import PursuitHandlers, wire_pursuit

__all__ = [
    "PursuitHandlers",
    "register_pursuit_projections",
    "register_pursuit_routes",
    "register_pursuit_tools",
    "wire_pursuit",
]
