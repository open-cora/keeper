"""HTTP door for reading a dataset.

`GET /datasets/{dataset_id}`. Returns the run that produced the data and
the store's address for it, which is the whole of what a dataset record
is.

The reference goes back as the two halves it was stored as, nested the
way it arrives on the way in. A caller resolving it has to be resolving
the same string the store was given, and any normalisation on the way out
is a chance for the two to differ.

The state is folded from the stream on every call. A dataset is one row
today, so a summary table would be machinery maintained ahead of a need.
That changes with the query this context exists for, which is every
dataset a given run produced, and which a fold cannot serve because it
cannot name the stream to fold.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel

from keeper.custody.features.get_dataset.handler import Handler
from keeper.custody.features.get_dataset.query import GetDataset
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


class GetDatasetResponse(BaseModel):
    """A dataset as this system currently holds it."""

    dataset_id: UUID
    execution_id: UUID
    step_id: UUID
    external_ref: ExternalRefResponse


def _get_handler(request: Request) -> Handler:
    handler: Handler = request.app.state.custody.get_dataset
    return handler


router = APIRouter(tags=["custody"])


@router.get(
    "/datasets/{dataset_id}",
    response_model=GetDatasetResponse,
    responses={
        status.HTTP_403_FORBIDDEN: {
            "model": ErrorResponse,
            "description": "The calling principal may not read datasets.",
        },
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponse,
            "description": "No dataset has that id.",
        },
    },
    summary="Read a dataset",
)
async def get_dataset(
    dataset_id: UUID,
    handler: Annotated[Handler, Depends(_get_handler)],
    cid: Annotated[UUID, Depends(get_correlation_id)],
    principal_id: Annotated[UUID, Depends(get_principal_id)],
    surface_id: Annotated[UUID, Depends(get_surface_id)],
) -> GetDatasetResponse:
    dataset = await handler(
        GetDataset(dataset_id=dataset_id),
        principal_id=principal_id,
        correlation_id=cid,
        surface_id=surface_id,
    )
    return GetDatasetResponse(
        dataset_id=dataset.id,
        execution_id=dataset.execution_id,
        step_id=dataset.step_id,
        external_ref=ExternalRefResponse(
            scheme=dataset.external_ref.scheme,
            value=dataset.external_ref.value,
        ),
    )
