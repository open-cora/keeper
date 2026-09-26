"""One row per inquiry, and the port that reads those rows.

The other read path, and the one carrying the half of this aggregate's
purpose that a fold cannot serve. `read.py` rebuilds one inquiry by
replaying its stream, which answers a question that already names the
inquiry. What an operator actually asks names none: which questions are
still waiting, and which of them has something been thinking about for an
hour.

## Why a port rather than a pool

The rows live in `proj_counsel_inquiry_summary`, a table a background worker
maintains. A handler could read it through the kernel's connection pool, and
that does not work for the reason the sibling read models found first: the
MCP surface contract requires every published tool to be called successfully
in a walk, and those walks boot the application with in-memory adapters and
no database. A tool that refuses because there is no pool fails the walk, and
one answering "nothing is waiting" while questions wait is worse, because it
is wrong rather than unavailable.

## Why the objective is on the row and the parameters next door are not

A proposal's parameters are unbounded, so a page of fifty of them would be
mostly parameters. An objective is bounded at
`INQUIRY_OBJECTIVE_MAX_LENGTH`, and it is bounded partly so that it can ride
here: a list of questions with the questions taken out is a list of
identifiers, and nobody scanning for the one they care about can use it.

## Why the filter is the status and not a flag

A proposal's list filters on one bit, because a proposal is open or taken
and there is nothing in between. An inquiry has a middle: a thinker said it
had this one and has not come back. Collapsing that into "unanswered" would
hide the only state worth watching, since an inquiry nobody claimed is
waiting and one claimed an hour ago is probably orphaned.

Nothing here expires a claim. A thinker that died holding one leaves a row
that stays `Claimed`, and `claimed_at` is what lets a reader see how long it
has been. That is deliberately a view rather than a rule: a claim that timed
itself out would release work this system cannot prove was abandoned.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from keeper.counsel.aggregates.inquiry.state import InquiryConclusion, InquiryStatus


@dataclass(frozen=True)
class InquirySummary:
    """An inquiry as a list shows it.

    `conclusion`, `observed_step_count` and `execution_ended` are None while
    nothing has answered, exactly as on the aggregate, because the nulls ARE
    the status and a list that invented a second word for it would be a
    second spelling of the same fact.

    `created_at` is when the question was put. It is never a caller's claim:
    asking is an act this system performs, so the envelope's domain time is
    this system's own clock reading.

    `claimed_at` and `answered_at` are both the caller's claims, because a
    thinker takes work up and concludes on its own clock. Three timestamps
    on one row from two authorities, which is the R8 split showing up on the
    read side.
    """

    inquiry_id: UUID
    actor_id: UUID
    execution_id: UUID
    objective: str
    execution_step_count: int
    status: InquiryStatus
    conclusion: InquiryConclusion | None
    observed_step_count: int | None
    execution_ended: bool | None
    proposal_id: UUID | None
    created_at: datetime
    claimed_at: datetime | None
    answered_at: datetime | None


@dataclass(frozen=True)
class InquirySummaryPage:
    """One page of summaries, newest first, and how to ask for the next.

    `next_cursor` is None when this is the last page. It is opaque on
    purpose: it encodes the sort key of the final row, and a caller that
    takes it apart is depending on an ordering this is free to change.
    """

    items: list[InquirySummary]
    next_cursor: str | None


class InquirySummaryLookup(Protocol):
    """Read inquiries by something other than their id.

    Named `Lookup` because that is the shape this repository declares for a
    read port, in `test_port_naming_conventions.py`.
    """

    async def list_inquiries(
        self,
        *,
        status: InquiryStatus | None,
        limit: int,
        cursor: str | None,
    ) -> InquirySummaryPage:
        """Return one page of inquiries, newest first.

        `status` narrows to one of the three the fold derives, and None asks
        for every inquiry. Narrowing to `CLAIMED` is the staleness question,
        which is why the filter is the status rather than a flag for
        answered.

        `cursor` continues a previous page and comes from its
        `next_cursor`. A cursor that does not decode raises
        `InvalidCursorError`.
        """
        ...


__all__ = ["InquirySummary", "InquirySummaryLookup", "InquirySummaryPage"]
