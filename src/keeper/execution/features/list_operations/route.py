"""HTTP door for listing operations.

`GET /operations`, newest first, filterable by name and paged with an opaque
cursor. A collection on the path the defining endpoint posts to, matching
the run list beside it.

## The one that can return two

A name is not unique here, on purpose, so this is the endpoint most likely
to hand back two rows where a caller expected one. That is the honest
answer rather than a defect: the two operations differ in what they constrain,
and which one a run cites is what says how it was constrained. A caller
that needs one operation and gets two has found something worth looking at.

## What a row carries and what it does not

The schema is not here. It is the largest thing an operation holds and a page of
fifty would be a page of schemas; `GET /operations/{operation_id}` has it.

One timestamp rather than two, because an operation has one event and nothing
moves it afterwards.
"""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status
from pydantic import BaseModel

from keeper.execution.features.list_operations.handler import Handler
from keeper.execution.features.list_operations.query import (
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    ListOperations,
)
from keeper.infrastructure.request import (
    ErrorResponse,
    get_correlation_id,
    get_principal_id,
    get_surface_id,
)


class OperationSummaryResponse(BaseModel):
    """One operation, as a list shows it."""

    operation_id: UUID
    name: str
    created_at: datetime


class ListOperationsResponse(BaseModel):
    """A page of operations, and how to ask for the next one.

    `next_cursor` is null on the last page. It is opaque: it encodes the
    sort key of the final row, and a caller that decodes it is depending
    on an ordering this is free to change.
    """

    items: list[OperationSummaryResponse]
    next_cursor: str | None


def _get_handler(request: Request) -> Handler:
    handler: Handler = request.app.state.execution.list_operations
    return handler


router = APIRouter(tags=["execution"])


@router.get(
    "/operations",
    response_model=ListOperationsResponse,
    responses={
        status.HTTP_400_BAD_REQUEST: {
            "model": ErrorResponse,
            "description": "The name filter was empty, whitespace-only or over the bound.",
        },
        status.HTTP_403_FORBIDDEN: {
            "model": ErrorResponse,
            "description": "The calling principal may not read operations.",
        },
        status.HTTP_422_UNPROCESSABLE_CONTENT: {
            "model": ErrorResponse,
            "description": "The cursor did not come from a previous response.",
        },
    },
    summary="List operations",
)
async def list_operations(
    handler: Annotated[Handler, Depends(_get_handler)],
    cid: Annotated[UUID, Depends(get_correlation_id)],
    principal_id: Annotated[UUID, Depends(get_principal_id)],
    surface_id: Annotated[UUID, Depends(get_surface_id)],
    name: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
    cursor: Annotated[str | None, Query()] = None,
) -> ListOperationsResponse:
    page = await handler(
        ListOperations.with_name(name=name, limit=limit, cursor=cursor),
        principal_id=principal_id,
        correlation_id=cid,
        surface_id=surface_id,
    )
    return ListOperationsResponse(
        items=[
            OperationSummaryResponse(
                operation_id=summary.operation_id,
                name=summary.name.value,
                created_at=summary.created_at,
            )
            for summary in page.items
        ],
        next_cursor=page.next_cursor,
    )
