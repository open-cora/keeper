"""One row per plan, and the port that reads those rows.

The Run's sibling, and the same shape for the same reason: `read.py`
answers a question that names a plan, and this answers the ones that do
not. Which plan is called `count`, and what can be run at all.

## Why a name lookup cannot promise one answer

Two plans may deliberately share a name. The Plan state module says why:
one routine constrained two ways is two plans, and which one an
acquisition step cites is what says how it was constrained. So this
returns a page, and a caller asking by name has to decide what more than
one means.

That decision is the caller's and not this system's. An operator who
wants one answer pins a plan id; a caller that cannot choose refuses and
says so. Either is better than this picking quietly, which would mean
choosing for every caller on the strength of an ordering none of them
asked about.

## Why the row is so thin

`parameters_schema` is not here. It is unbounded, it is the largest thing
a plan carries, and a page of them is a page of schemas. A caller that
wants one has the plan id and one more call.

There is no `updated_at` either, and that is not a choice the way it is
on a row whose record changes. A plan has one event. Nothing changes it,
so a second timestamp could never differ from the first, and a column
that cannot differ invites a reader to believe a lifecycle is being
tracked.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from keeper.execution.aggregates.plan.state import PlanName


@dataclass(frozen=True)
class PlanSummary:
    """A plan as a list shows it.

    `created_at` is when the plan was defined, taken from the envelope's
    domain time. For a plan the two times the envelope carries are the
    same instant to within a round trip, because a plan is authored here
    rather than reported from somewhere else, which is the R8 line the
    whole context is drawn along.
    """

    plan_id: UUID
    name: PlanName
    created_at: datetime


@dataclass(frozen=True)
class PlanSummaryPage:
    """One page of summaries, newest first, and how to ask for the next.

    `next_cursor` is None when this is the last page. Opaque on purpose:
    it encodes the sort key of the final row, and a caller that takes it
    apart is depending on an ordering this is free to change.
    """

    items: list[PlanSummary]
    next_cursor: str | None


class PlanSummaryLookup(Protocol):
    """Read plans by something other than their id."""

    async def list_plans(
        self,
        *,
        name: PlanName | None,
        limit: int,
        cursor: str | None,
    ) -> PlanSummaryPage:
        """Return one page of plans, newest first.

        `name` narrows to the plans carrying exactly that name, which may
        be none, one, or several, and the several is the case worth
        designing for.

        `cursor` continues a previous page and comes from its
        `next_cursor`. A cursor that does not decode raises
        `InvalidCursorError`.
        """
        ...


__all__ = ["PlanSummary", "PlanSummaryLookup", "PlanSummaryPage"]
