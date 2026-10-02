"""One row per step, and the port that reads those rows.

The third read path on this aggregate. `read.py` rebuilds one execution
by replaying its stream, `summary.py` lists executions without their
steps, and this lists the steps themselves.

The gap it fills is narrow and was load-bearing. An execution summary
drops the steps because a page of fifty executions would otherwise be
almost entirely steps, so "what did this execution actually run, and
what came out of each step" had no answer short of folding the stream,
and "which runs produced data nothing recorded" had none at all.

## Why a step row carries a dataset

`dataset_id` is Custody's fact. It is here because the question that
justifies this read model is about the two together, and because
nothing else can pair them: a step report names its step by index and a
dataset names it by id, so only the dispatch that fixed the list can
say which is which.

A read model may span two contexts where an aggregate may not. Nothing
on Execution's write side can see a dataset, this table is derived, and
it can be dropped and rebuilt from the log. The alternative was to put
every step of every execution behind Custody's read surface, which has
no aggregate to hang them from.

## Why a port rather than a pool

The rows live in `proj_execution_step_summary`, a table a background
worker maintains. The MCP surface contract requires every published
tool to be called successfully in a walk, and those walks boot the
application with in-memory adapters and no database. A tool that
refuses for want of a pool fails that walk, and one that answers "no
steps" while steps exist is worse, because it is wrong rather than
unavailable.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from keeper.execution.aggregates.execution.state import ExecutionBeamline


@dataclass(frozen=True)
class StepSummary:
    """One step of one execution, and what is known to have come of it.

    `describes` is the sentence the dispatch fixed, copied so a reader
    of this row does not need the procedure to know what the step was.
    It is the whole reason a gap in this listing is actionable: a path
    and an execution id say a dataset is missing, and the sentence says
    which piece of work it was missing from.

    `outcome` is None for a step nothing has reported yet, which is an
    ordinary state rather than a fault: an execution reports its steps
    one at a time and the rows for the rest exist from the dispatch.

    `engine_reference` is what the engine called the run this step
    opened. None for a step that opened none, which covers a move, a
    step that was refused or broken, one never reached, and a run whose
    engine had no name to give.

    `run_opened_at` is when something watching the engine saw the run
    begin, and None means nothing was watching. It reads like a detail
    and is the difference between the two failures this listing
    returns. A run with a time behind it ran under observation and its
    data went unrecorded, which is a filing or engine fault. A run with
    none ran at a beamline where nobody was reporting, which is a
    deployment fault, loses every run rather than one, and is the case
    this listing could not see at all while it gated on this column
    instead of returning it.

    `dataset_id` is the record of where that run's output is being kept,
    and None means nothing holds it. A reference with no dataset is the
    gap this row exists to make findable: the work ran, the data was
    written, and no part of this system can say where.

    `filed_at` is when that record was made, not when the data was
    written. The dataset itself carries the second, which is the
    caller's own report of when the store finished.
    """

    step_id: UUID
    execution_id: UUID
    index: int
    describes: str
    beamline: ExecutionBeamline
    outcome: str | None
    engine_reference: str | None
    reported_at: datetime | None
    run_opened_at: datetime | None
    dataset_id: UUID | None
    filed_at: datetime | None


@dataclass(frozen=True)
class StepSummaryPage:
    """One page of steps, newest first, and how to ask for the next.

    `next_cursor` is None when this is the last page. It is opaque on
    purpose: it encodes the sort key of the final row, and a caller that
    takes it apart is depending on an ordering this is free to change.
    """

    items: list[StepSummary]
    next_cursor: str | None


class StepSummaryLookup(Protocol):
    """Read the steps of executions by something other than a step id.

    Named `Lookup` because that is the shape this repository declares
    for a read port, in `test_port_naming_conventions.py`.
    """

    async def list_steps_without_datasets(
        self,
        *,
        beamline: ExecutionBeamline | None,
        limit: int,
        cursor: str | None,
    ) -> StepSummaryPage:
        """Return one page of runs whose output nothing recorded.

        Every row has an `engine_reference` and no `dataset_id`: a step
        that opened a run the engine named, and no record of where that
        run's output went. Ordered by when the step was reported, newest
        first, because the useful reading is what has gone unrecorded
        lately rather than the oldest gap in the log.

        Steps that opened no run are not here at all. A move records
        nothing and is not missing anything, so counting it would make
        the answer to this question grow with the size of every
        procedure.

        `beamline` narrows to one station, which is how somebody
        responsible for one asks. None spans the facility.

        This is not a list of lost data. A gap means nothing recorded
        where the output is, and the output is wherever the engine put
        it: on disk, under the reference in the row. What is missing is
        the record, which is also why a row can stop being a gap later
        without anything being re-run.

        `cursor` continues a previous page and comes from its
        `next_cursor`. A cursor that does not decode raises
        `InvalidCursorError`.
        """
        ...


__all__ = ["StepSummary", "StepSummaryLookup", "StepSummaryPage"]
