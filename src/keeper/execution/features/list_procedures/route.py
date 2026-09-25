"""HTTP door for listing procedures.

`GET /procedures`, newest first, filterable by name and paged with an
opaque cursor. A collection on the path the defining endpoint posts to,
matching the plan list beside it.

## What a row carries and what it does not

The steps are not here. A procedure may hold a thousand, so a page of
fifty would be almost entirely steps. What a list needs instead is how
long the routine is, which is `step_count`, and
`GET /procedures/{procedure_id}` has the rest.

One timestamp rather than two, because a procedure has one event and
nothing moves it afterwards.
"""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status
from pydantic import BaseModel

from keeper.execution.features.list_procedures.handler import Handler
from keeper.execution.features.list_procedures.query import (
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    ListProcedures,
)
from keeper.infrastructure.request import (
    ErrorResponse,
    get_correlation_id,
    get_principal_id,
    get_surface_id,
)


class ProcedureSummaryResponse(BaseModel):
    """One procedure, as a list shows it."""

    procedure_id: UUID
    name: str
    beamline: str
    step_count: int
    created_at: datetime


class ListProceduresResponse(BaseModel):
    """A page of procedures, and how to ask for the next one.

    `next_cursor` is null on the last page. It is opaque: it encodes the
    sort key of the final row, and a caller that decodes it is depending
    on an ordering this is free to change.
    """

    items: list[ProcedureSummaryResponse]
    next_cursor: str | None


def _get_handler(request: Request) -> Handler:
    handler: Handler = request.app.state.execution.list_procedures
    return handler


router = APIRouter(tags=["execution"])


@router.get(
    "/procedures",
    response_model=ListProceduresResponse,
    responses={
        status.HTTP_400_BAD_REQUEST: {
            "model": ErrorResponse,
            "description": "The name filter was empty, whitespace-only or over the bound.",
        },
        status.HTTP_403_FORBIDDEN: {
            "model": ErrorResponse,
            "description": "The calling principal may not read procedures.",
        },
        status.HTTP_422_UNPROCESSABLE_CONTENT: {
            "model": ErrorResponse,
            "description": "The cursor did not come from a previous response.",
        },
    },
    summary="List procedures",
)
async def list_procedures(
    handler: Annotated[Handler, Depends(_get_handler)],
    cid: Annotated[UUID, Depends(get_correlation_id)],
    principal_id: Annotated[UUID, Depends(get_principal_id)],
    surface_id: Annotated[UUID, Depends(get_surface_id)],
    name: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
    cursor: Annotated[str | None, Query()] = None,
) -> ListProceduresResponse:
    page = await handler(
        ListProcedures.with_name(name=name, limit=limit, cursor=cursor),
        principal_id=principal_id,
        correlation_id=cid,
        surface_id=surface_id,
    )
    return ListProceduresResponse(
        items=[
            ProcedureSummaryResponse(
                procedure_id=summary.procedure_id,
                name=summary.name.value,
                beamline=summary.beamline.value,
                step_count=summary.step_count,
                created_at=summary.created_at,
            )
            for summary in page.items
        ],
        next_cursor=page.next_cursor,
    )
