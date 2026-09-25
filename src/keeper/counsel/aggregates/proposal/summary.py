"""One row per proposal, and the port that reads those rows.

The other read path, and the one carrying this context's purpose.
`read.py` rebuilds one proposal by replaying its stream, which answers a
question that already names the proposal. The question the context
exists for names no proposal at all: which of them is still open. A fold
has to know which stream to fold, and that is exactly what is being
asked.

So `get_proposal` shipped first only because it is the half a fold can
serve.

## Why a port rather than a pool

The rows live in `proj_counsel_proposal_summary`, a table a background
worker maintains. A handler could read it through the kernel's
connection pool, and that does not work for the reason the sibling
contexts found first: the MCP surface contract requires every published
tool to be called successfully in a walk, and those walks boot the
application with in-memory adapters and no database. A tool that refuses
because there is no pool fails the execution, and one answering "no
proposals" while proposals exist is worse, because it is wrong rather
than unavailable.

## What a summary leaves out

The parameters, and only those. They are unbounded, and a page of fifty
rows would be mostly parameters, which is the same call the run summary
makes for the same reason. Everything else on the record is an id.

A caller that wants the values reads the one proposal it cares about.
That is the ordinary shape: a list is for finding something, and finding
it is what tells you which id to read.

## Why the filter is openness and not the other three

`is_open` is the question this table was built for. Filters on the
proposer, on the plan, and on a date range are each a column that
already exists and a parameter that does not, and none has a caller: an
agent holds the ids of its own proposals, and an operator asking what
nobody acted on is asking exactly what `is_open` answers. Each is a
parameter and an index when somebody needs it.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True)
class ProposalSummary:
    """A proposal as a list shows it.

    `execution_id` and `step_id` are None while the proposal is open,
    exactly as on the aggregate, because the null IS the status and a
    list that invented a status word would be a second spelling of it.

    `created_at` is when the proposal was made. Unlike a dataset's, it is
    never a caller's claim: making one is an act this system performs, so
    the envelope's domain time is this system's own clock reading.

    `taken_at` is when an acquisition took it, and None while it is
    open. This is the caller's claim, because the step was driven
    somewhere else, so the two timestamps on one row come from different
    authorities. That is the R8 split showing up on the read side.
    """

    proposal_id: UUID
    actor_id: UUID
    plan_id: UUID
    execution_id: UUID | None
    step_id: UUID | None
    created_at: datetime
    taken_at: datetime | None


@dataclass(frozen=True)
class ProposalSummaryPage:
    """One page of summaries, newest first, and how to ask for the next.

    `next_cursor` is None when this is the last page. It is opaque on
    purpose: it encodes the sort key of the final row, and a caller that
    takes it apart is depending on an ordering this is free to change.
    """

    items: list[ProposalSummary]
    next_cursor: str | None


class ProposalSummaryLookup(Protocol):
    """Read proposals by something other than their id.

    Named `Lookup` because that is the shape this repository declares for
    a read port, in `test_port_naming_conventions.py`.
    """

    async def list_proposals(
        self,
        *,
        is_open: bool | None,
        limit: int,
        cursor: str | None,
    ) -> ProposalSummaryPage:
        """Return one page of proposals, newest first.

        `is_open` narrows to proposals with no acquisition against them,
        which is the question this context exists to answer. False
        narrows to the ones a step took, and None asks for every
        proposal.

        It is spelled as the positive form of the question people ask,
        where the aggregate spells the same bit as `is_taken` beside the
        event that sets it. Both words are in the glossary and each is
        right where it sits: an event is named for what happened, and a
        filter is named for what a caller is looking for.

        `cursor` continues a previous page and comes from its
        `next_cursor`. A cursor that does not decode raises
        `InvalidCursorError`.
        """
        ...


__all__ = ["ProposalSummary", "ProposalSummaryLookup", "ProposalSummaryPage"]
