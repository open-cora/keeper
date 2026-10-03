"""HTTP door for reading a dataset.

`GET /datasets/{dataset_id}`. Returns the run that produced the data,
the store's address for it, and what somebody found inside it if
anybody has looked.

The description is the one part a caller must read as of a moment
rather than as now. It carries the copy it was taken of and when, so a
reader can tell an early look from a later one, and this surface does
not interpret either. A dataset nobody has described comes back with
none, which says nothing was reported rather than that the data is
empty.

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

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel

from keeper.custody.aggregates.dataset import Description
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


class ExtentResponse(BaseModel):
    """How much of something there is, and of what.

    With a `dtype` the shape is an array's dimensions. Without one it
    is a single count of what a region holds. Absent entirely where
    whatever described this did not measure it.
    """

    shape: list[int]
    capacity: list[int] | None
    dtype: str | None


class EntryResponse(BaseModel):
    """One thing inside the data, and what a convention calls it.

    A missing entry is the most useful thing this can carry: a report
    says what was there, never what a convention says should be there.
    A `role` of null means nobody named it, which is not the same as
    there being nothing to name.
    """

    path: str
    extent: ExtentResponse | None
    role: str | None


class DescriptionResponse(BaseModel):
    """What was inside one copy of the data when somebody looked.

    `described_at` is when the container was read, and the whole of
    this is a statement about that moment. It does not claim to be
    current and nothing here refreshes it.
    """

    external_ref: ExternalRefResponse
    convention: str
    entries: list[EntryResponse]
    described_at: datetime


class GetDatasetResponse(BaseModel):
    """A dataset as this system currently holds it."""

    dataset_id: UUID
    execution_id: UUID
    step_id: UUID
    external_refs: list[ExternalRefResponse]
    description: DescriptionResponse | None


def _get_handler(request: Request) -> Handler:
    handler: Handler = request.app.state.custody.get_dataset
    return handler


def _described(description: Description | None) -> DescriptionResponse | None:
    if description is None:
        return None
    return DescriptionResponse(
        external_ref=ExternalRefResponse(
            scheme=description.external_ref.scheme, value=description.external_ref.value
        ),
        convention=description.manifest.convention,
        entries=[
            EntryResponse(
                path=entry.path,
                extent=None
                if entry.extent is None
                else ExtentResponse(
                    shape=list(entry.extent.shape),
                    capacity=None if entry.extent.capacity is None else list(entry.extent.capacity),
                    dtype=entry.extent.dtype,
                ),
                role=entry.role,
            )
            for entry in description.manifest.entries
        ],
        described_at=description.described_at,
    )


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
        external_refs=[
            ExternalRefResponse(scheme=ref.scheme, value=ref.value) for ref in dataset.external_refs
        ],
        description=_described(dataset.description),
    )
