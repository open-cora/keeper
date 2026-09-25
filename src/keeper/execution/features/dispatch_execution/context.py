"""The sibling state this slice's decision needs, loaded before deciding.

A decider is pure and never reads from a store. Dispatching copies a
procedure's name and steps onto the execution's genesis, and the procedure is
a different stream, so the handler does the reading and hands it across
as plain data.

The sibling of `define_procedure`'s, which loads a plan per acquisition
where this one loads the single procedure being handed out.
"""

from dataclasses import dataclass

from keeper.execution.aggregates.procedure import Procedure


@dataclass(frozen=True)
class DispatchExecutionContext:
    """The procedure being dispatched, as it stands right now.

    Read at handler time. A procedure has one event and nothing edits it,
    so unlike the plan a run reads this one cannot have changed between
    the read and the append. What it can be is absent, and the handler
    refuses that before building this.
    """

    procedure: Procedure


__all__ = ["DispatchExecutionContext"]
