"""HTTP door for listing executions.

`GET /executions`, newest first, narrowed by procedure, by beamline, by
status, or by any combination of the three.

The steps are not on these rows. A page of fifty executions carrying up to a
thousand steps each would be almost entirely steps, and how far an execution
got is two integers.

## The work intake, and why this route can hold a request open

One caller of this route is not a person. Something at a beamline asks
for the executions dispatched to it that nothing has taken up, and it
asks continuously, because that is how it learns there is work. Answered
the ordinary way, that is a poll: a request every few seconds, almost
all of them empty, and a pickup delay of half the interval.

`wait` makes it a long poll instead. The request is held open until a
dispatch appears or the wait runs out, so a conductor sits on one open
connection rather than asking repeatedly, and work reaches it in
milliseconds rather than at the next tick.

The bound is a socket keepalive ceiling and not a latency budget.
Connections held open indefinitely die in proxies and NAT tables without
telling either end, so the request returns empty at the ceiling and the
caller opens another. Nothing is lost in the gap between the two: a
dispatch landing there is sitting at `Dispatched` in the database, and
the next request returns it.

**The signal is an optimization and the query is the truth.** A notify
can be missed, which `waiting` explains, so each wait is itself
bounded and the query runs again after it. A missed signal costs latency
until the next look rather than a dispatch nobody picks up.

`wait` is on this surface and not on the MCP tool. The intake is an HTTP
client, and an agent holding a tool call open for half a minute is a
different thing wanting a different answer.
"""

from datetime import datetime
from typing import Annotated, Final
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status
from pydantic import BaseModel

from keeper.execution.aggregates.execution import ExecutionBeamline, ExecutionStatus
from keeper.execution.aggregates.execution.summary import ExecutionSummaryPage
from keeper.execution.features.list_executions.handler import Handler
from keeper.execution.features.list_executions.query import (
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    ListExecutions,
)
from keeper.execution.waiting import await_a_dispatch
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
seconds is the intake's usual ask; this leaves room above it and refuses
the caller who would hold a connection for an hour.
"""


def _get_signal(request: Request) -> WakeupSource:
    """The wake-up source the application's lifespan is holding open."""
    signal: WakeupSource = request.app.state.dispatch_signal
    return signal


def _get_handler(request: Request) -> Handler:
    handler: Handler = request.app.state.execution.list_executions
    return handler


class ExecutionSummaryResponse(BaseModel):
    """An execution as a list shows it.

    `reported_count` against `step_count` is how far it got and `status`
    says what is happening to it. A `Running` execution with the two unequal
    is either still going or was abandoned, and nothing here can tell
    those apart. A `Dispatched` one with an old `created_at` is the
    other row worth looking at: nothing ever took it up.
    """

    execution_id: UUID
    procedure_id: UUID
    procedure_name: str
    beamline: str
    step_count: int
    reported_count: int
    status: ExecutionStatus
    created_at: datetime
    updated_at: datetime


class ListExecutionsResponse(BaseModel):
    """One page, and the cursor that continues it."""

    items: list[ExecutionSummaryResponse]
    next_cursor: str | None


router = APIRouter(tags=["execution"])


@router.get(
    "/executions",
    response_model=ListExecutionsResponse,
    responses={
        status.HTTP_400_BAD_REQUEST: {
            "model": ErrorResponse,
            "description": "The cursor was not well-formed.",
        },
        status.HTTP_403_FORBIDDEN: {
            "model": ErrorResponse,
            "description": "The calling principal may not read executions.",
        },
        status.HTTP_422_UNPROCESSABLE_CONTENT: {
            "model": ErrorResponse,
            "description": "The cursor did not come from a previous response.",
        },
    },
    summary="List executions",
)
async def list_executions(
    handler: Annotated[Handler, Depends(_get_handler)],
    cid: Annotated[UUID, Depends(get_correlation_id)],
    principal_id: Annotated[UUID, Depends(get_principal_id)],
    surface_id: Annotated[UUID, Depends(get_surface_id)],
    signal: Annotated[WakeupSource, Depends(_get_signal)],
    procedure_id: Annotated[UUID | None, Query()] = None,
    beamline: Annotated[
        str | None,
        Query(
            description="Only the executions dispatched to this beamline, such as 2-bm. "
            "How a conductor asks for work it can drive.",
        ),
    ] = None,
    status: Annotated[
        ExecutionStatus | None,
        Query(
            description="Only the executions in this status. Dispatched is the one "
            "nothing has taken up yet.",
        ),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
    cursor: Annotated[str | None, Query()] = None,
    wait: Annotated[
        float,
        Query(
            ge=0,
            le=MAX_WAIT_SECONDS,
            description="Hold the request open for up to this many seconds rather than "
            "answering an empty page, and return as soon as anything matches. How the "
            "work intake waits for a dispatch without polling. Zero answers at once.",
        ),
    ] = 0.0,
) -> ListExecutionsResponse:
    query = ListExecutions(
        procedure_id=procedure_id,
        beamline=ExecutionBeamline(beamline) if beamline is not None else None,
        status=status,
        limit=limit,
        cursor=cursor,
    )

    async def read() -> ExecutionSummaryPage:
        return await handler(
            query,
            principal_id=principal_id,
            correlation_id=cid,
            surface_id=surface_id,
        )

    page = await read()
    if not page.items and wait > 0:
        page = await await_a_dispatch(read, signal, wait)

    return ListExecutionsResponse(
        items=[
            ExecutionSummaryResponse(
                execution_id=summary.execution_id,
                procedure_id=summary.procedure_id,
                procedure_name=summary.procedure_name,
                beamline=summary.beamline.value,
                step_count=summary.step_count,
                reported_count=summary.reported_count,
                status=summary.status,
                created_at=summary.created_at,
                updated_at=summary.updated_at,
            )
            for summary in page.items
        ],
        next_cursor=page.next_cursor,
    )
