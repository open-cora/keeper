"""One row per procedure, and the port that reads those rows.

The Plan's sibling, and the same shape for the same reason: `read.py`
answers a question that names a procedure, and this answers the ones
that do not. Which procedure is called `tomography`, and what has been
composed at all.

## Why a name lookup cannot promise one answer

Two procedures may share a name, for the reason two plans may: one
routine composed two ways is two procedures, and which one an execution
cites is what says how it was composed. So this returns a page, and a
caller asking by name has to decide what more than one means. That
decision is the caller's; this picking quietly would mean choosing on
the strength of an ordering nobody asked about.

## Why the steps are not on the row

A procedure may hold a thousand of them, so a page of fifty would be
almost entirely steps. What a list needs instead is how long the routine
is, which is one integer, and a caller that wants the steps has the id
and one more call. That is the same split `GET /executions` already draws.

There is no `updated_at`. A procedure has one event, so a second
timestamp could never differ from the first, and a column that cannot
differ invites a reader to believe a lifecycle is being tracked.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from keeper.execution.aggregates.procedure.state import ProcedureBeamline, ProcedureName


@dataclass(frozen=True)
class ProcedureSummary:
    """A procedure as a list shows it.

    `created_at` is when the procedure was defined, taken from the
    envelope's domain time. For a procedure the two times the envelope
    carries are the same instant to within a round trip, because a
    procedure is authored here rather than reported from somewhere else,
    which is the R8 line the whole context is drawn along.
    """

    procedure_id: UUID
    name: ProcedureName
    beamline: ProcedureBeamline
    step_count: int
    created_at: datetime


@dataclass(frozen=True)
class ProcedureSummaryPage:
    """One page of summaries, newest first, and how to ask for the next.

    `next_cursor` is None when this is the last page. Opaque on purpose:
    it encodes the sort key of the final row, and a caller that takes it
    apart is depending on an ordering this is free to change.
    """

    items: list[ProcedureSummary]
    next_cursor: str | None


class ProcedureSummaryLookup(Protocol):
    """Read procedures by something other than their id."""

    async def list_procedures(
        self,
        *,
        name: ProcedureName | None,
        limit: int,
        cursor: str | None,
    ) -> ProcedureSummaryPage:
        """Return one page of procedures, newest first.

        `name` narrows to the procedures carrying exactly that name,
        which may be none, one, or several.

        `cursor` continues a previous page and comes from its
        `next_cursor`. A cursor that does not decode raises
        `InvalidCursorError`.
        """
        ...


__all__ = ["ProcedureSummary", "ProcedureSummaryLookup", "ProcedureSummaryPage"]
