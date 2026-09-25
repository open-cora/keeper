"""HTTP door for finding datasets.

`GET /datasets`, optionally narrowed to one run, newest first, paged.

The read that carries this context's purpose. `GET /datasets/{id}` answers
a question that already names the dataset; this one answers "what did this
run produce", which is what somebody holding a run actually has.

Rows carry `created_at`, and the single read carries no timestamp at all.
That is a decision on each side rather than an oversight on one: a list is
read to find something, and when data was written is how a person
recognises the one they meant. A single read already names the dataset, so
the question is answered before the timestamp could help.
"""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status
from pydantic import BaseModel

from keeper.custody.features.list_datasets.handler import Handler
from keeper.custody.features.list_datasets.query import (
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    ListDatasets,
)
from keeper.infrastructure.request import (
    ErrorResponse,
    get_correlation_id,
    get_principal_id,
    get_surface_id,
)


class ExternalRefResponse(BaseModel):
    """What the store holding this data calls it."""

    scheme: str
    value: str


class DatasetSummaryResponse(BaseModel):
    """A dataset as a list shows it."""

    dataset_id: UUID
    execution_id: UUID
    step_id: UUID
    external_ref: ExternalRefResponse
    created_at: datetime


class ListDatasetsResponse(BaseModel):
    """One page, and how to ask for the next.

    `next_cursor` is null on the last page. It is opaque: it encodes the
    sort key of the final row, and a caller taking it apart is depending
    on an ordering this is free to change.
    """

    items: list[DatasetSummaryResponse]
    next_cursor: str | None


def _get_handler(request: Request) -> Handler:
    handler: Handler = request.app.state.custody.list_datasets
    return handler


router = APIRouter(tags=["custody"])


@router.get(
    "/datasets",
    response_model=ListDatasetsResponse,
    responses={
        status.HTTP_403_FORBIDDEN: {
            "model": ErrorResponse,
            "description": "The calling principal may not read datasets.",
        },
        status.HTTP_422_UNPROCESSABLE_CONTENT: {
            "model": ErrorResponse,
            "description": "The cursor is not one this system issued.",
        },
    },
    summary="Find datasets",
)
async def get_datasets(
    handler: Annotated[Handler, Depends(_get_handler)],
    cid: Annotated[UUID, Depends(get_correlation_id)],
    principal_id: Annotated[UUID, Depends(get_principal_id)],
    surface_id: Annotated[UUID, Depends(get_surface_id)],
    step_id: Annotated[
        UUID | None,
        Query(description="Only datasets this run produced."),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
    cursor: Annotated[str | None, Query(description="Continue a previous page.")] = None,
) -> ListDatasetsResponse:
    page = await handler(
        ListDatasets(step_id=step_id, limit=limit, cursor=cursor),
        principal_id=principal_id,
        correlation_id=cid,
        surface_id=surface_id,
    )
    return ListDatasetsResponse(
        items=[
            DatasetSummaryResponse(
                dataset_id=summary.dataset_id,
                execution_id=summary.execution_id,
                step_id=summary.step_id,
                external_ref=ExternalRefResponse(
                    scheme=summary.external_ref.scheme,
                    value=summary.external_ref.value,
                ),
                created_at=summary.created_at,
            )
            for summary in page.items
        ],
        next_cursor=page.next_cursor,
    )
