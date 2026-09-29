"""HTTP door for finding inquiries.

`GET /inquiries`, newest first, one page at a time.

`status` is the filter, and `Claimed` is the one worth knowing about: it
narrows to questions something said it was thinking about. Nothing expires
a claim, so a row that has sat there since yesterday is how an abandoned
thinker becomes visible. That is deliberately a view rather than a rule,
since a claim that timed itself out would release work this system cannot
prove was abandoned.

The objective rides on every row, unlike the proposal listing's
parameters. It is bounded, and it is bounded partly so it can: a list of
questions with the questions taken out is a list of identifiers.

## Why this route can hold a request open

One caller of this route is not a person. Something that thinks asks for
the questions nobody has taken up, and it asks continuously, because
that is how it learns there is work. Answered the ordinary way, that is
a poll: a request every few seconds, almost all of them empty, and a
pickup delay of half the interval.

`wait` makes it a long poll instead. The request is held open until a
question appears or the wait runs out, so a thinker sits on one open
connection rather than asking repeatedly, and a question reaches it in
milliseconds rather than at the next tick.

The bound is a socket keepalive ceiling and not a latency budget.
Connections held open indefinitely die in proxies and NAT tables without
telling either end, so the request returns empty at the ceiling and the
caller opens another. Nothing is lost in the gap between the two: a
question landing there is sitting at Open in the database, and the next
request returns it.

**The signal is an optimization and the query is the truth.** A notify
can be missed, which `waiting` explains, so each wait is itself bounded
and the query runs again after it. A missed signal costs latency until
the next look rather than a question nobody picks up.

`wait` is on this surface and not on the MCP tool, which is the call the
execution listing makes. A thinker going looking is an HTTP client, and
an agent holding a tool call open for half a minute is a different thing
wanting a different answer.
"""

from datetime import datetime
from typing import Annotated, Final
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status
from pydantic import BaseModel

from keeper.counsel.aggregates.inquiry import InquiryConclusion, InquiryStatus
from keeper.counsel.aggregates.inquiry.summary import InquirySummaryPage
from keeper.counsel.features.list_inquiries.handler import Handler
from keeper.counsel.features.list_inquiries.query import (
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    ListInquiries,
)
from keeper.infrastructure.projection.long_poll import await_a_row
from keeper.infrastructure.projection.wakeup import WakeupSource
from keeper.infrastructure.request import (
    ErrorResponse,
    get_correlation_id,
    get_principal_id,
    get_surface_id,
)

MAX_WAIT_SECONDS: Final = 60.0
"""The longest a caller may ask this route to hold its request open.

A ceiling on the socket rather than on the wait anybody wants. Thirty
seconds is a thinker's usual ask; this leaves room above it and refuses
the caller who would hold a connection for an hour.

The same number the execution listing allows, and the same for a reason
rather than by coincidence: what it bounds is how long any connection
through this system may sit idle, which is a property of the deployment
and not of what is being waited for.
"""


class InquirySummaryResponse(BaseModel):
    """An inquiry as a list shows it."""

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


class ListInquiriesResponse(BaseModel):
    """One page of inquiries, and how to ask for the next."""

    items: list[InquirySummaryResponse]
    next_cursor: str | None


def _get_signal(request: Request) -> WakeupSource:
    """The wake-up source the application's lifespan is holding open."""
    signal: WakeupSource = request.app.state.inquiry_signal
    return signal


def _get_handler(request: Request) -> Handler:
    handler: Handler = request.app.state.counsel.list_inquiries
    return handler


router = APIRouter(tags=["counsel"])


@router.get(
    "/inquiries",
    response_model=ListInquiriesResponse,
    responses={
        status.HTTP_403_FORBIDDEN: {
            "model": ErrorResponse,
            "description": "The calling principal may not read inquiries.",
        },
        status.HTTP_422_UNPROCESSABLE_CONTENT: {
            "model": ErrorResponse,
            "description": "The cursor is not one this system issued.",
        },
    },
    summary="Find inquiries",
)
async def get_inquiries(
    handler: Annotated[Handler, Depends(_get_handler)],
    cid: Annotated[UUID, Depends(get_correlation_id)],
    principal_id: Annotated[UUID, Depends(get_principal_id)],
    surface_id: Annotated[UUID, Depends(get_surface_id)],
    signal: Annotated[WakeupSource, Depends(_get_signal)],
    inquiry_status: Annotated[
        InquiryStatus | None,
        Query(
            alias="status",
            description="Open for questions nothing has taken up, Claimed for ones "
            "something is thinking about, Answered for ones a thinker came back to.",
        ),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
    cursor: Annotated[str | None, Query(description="Continue a previous page.")] = None,
    wait: Annotated[
        float,
        Query(
            ge=0,
            le=MAX_WAIT_SECONDS,
            description="Hold the request open for up to this many seconds rather than "
            "answering an empty page, and return as soon as anything matches. How a "
            "thinker waits for a question without polling. Zero answers at once.",
        ),
    ] = 0.0,
) -> ListInquiriesResponse:
    query = ListInquiries(status=inquiry_status, limit=limit, cursor=cursor)

    async def read() -> InquirySummaryPage:
        return await handler(
            query,
            principal_id=principal_id,
            correlation_id=cid,
            surface_id=surface_id,
        )

    page = await read()
    if not page.items and wait > 0:
        page = await await_a_row(read, signal, wait)

    return ListInquiriesResponse(
        items=[
            InquirySummaryResponse(
                inquiry_id=summary.inquiry_id,
                actor_id=summary.actor_id,
                execution_id=summary.execution_id,
                objective=summary.objective,
                execution_step_count=summary.execution_step_count,
                status=summary.status,
                conclusion=summary.conclusion,
                observed_step_count=summary.observed_step_count,
                execution_ended=summary.execution_ended,
                proposal_id=summary.proposal_id,
                created_at=summary.created_at,
                claimed_at=summary.claimed_at,
                answered_at=summary.answered_at,
            )
            for summary in page.items
        ],
        next_cursor=page.next_cursor,
    )
