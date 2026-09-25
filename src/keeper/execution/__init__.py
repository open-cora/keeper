"""Execution bounded context.

Owns what this system can be asked to run, what it composed out of that,
and what happened when it was carried out.

    plan        a routine an engine already has, by the name that engine
                knows it by, and the schema its parameters must satisfy.

    procedure   a routine this system composed: ordered steps, each of
                them a move or an acquisition citing a plan.

    execution   one traversal of a procedure: the steps it was asked to
                perform, and how each of them ended.

Three aggregates in one context because none of them can be checked
without the others. An acquisition's parameters are checked against the
plan it cites, and a dispatch copies a procedure's steps onto the record
it opens. Across a context boundary each of those would have to reach
through a sibling's read-side surface for a relationship neither side
can be without.

## Who drove the act

**This system owns every genesis.** It writes the plan, composes the
procedure and opens the execution, and a client outside can only move
what it created. That is the whole of the posture, and it arrived by
replacing one where an outside caller could bring a record into
existence by reporting a run that had already happened.

What still comes from outside is how the work went, on two channels that
can disagree. A driver says what it observed of each step, and whatever
watches an engine says what that engine did to the run one acquisition
opened. Both are relayed claims rather than things this system saw, and
neither is treated as the other's correction: `ExecutionStep` carries
both.

Reported rather than witnessed, which was the first word here and was
wrong. To witness is to have been present and able to vouch for what
happened. This system is neither. It is told, and the whole of what it
knows is that it was told. A word claiming more than that would be the
kind of unbacked claim this tree refuses everywhere else.
"""

from keeper.execution.aggregates.execution import Execution, load_execution
from keeper.execution.aggregates.plan import Plan, load_plan
from keeper.execution.errors import UnauthorizedError
from keeper.execution.projections import register_execution_projections
from keeper.execution.routes import register_execution_routes
from keeper.execution.tools import register_execution_tools
from keeper.execution.wire import ExecutionHandlers, wire_execution

__all__ = [
    "Execution",
    "ExecutionHandlers",
    "Plan",
    "UnauthorizedError",
    "load_execution",
    "load_plan",
    "register_execution_projections",
    "register_execution_routes",
    "register_execution_tools",
    "wire_execution",
]
