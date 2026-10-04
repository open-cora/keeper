"""HTTP door for registering a description of a dataset.

`POST /datasets/{dataset_id}/manifests`, carrying the copy that was
opened and what was found inside it.

A collection, like the addresses beside it, because a dataset can be
described more than once and each report is its own statement about a
moment. What the record folds to is the latest, which is a reading of
the history rather than a thing this surface promises.

`204`, because a description has no id of its own. It is identified by
the dataset and the copy, both of which the caller already holds.

Everything nests rather than flattening into top-level keys, so a body
cannot express half a reference or an entry whose extent is half
given.

The bounds on the strings are declared here as well as on the value
objects: these turn an over-long path into FastAPI's standard 422
before a command exists, and the value objects are what hold for the
MCP surface and for anything replaying the log.
"""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel, Field

from keeper.custody.aggregates.dataset import (
    ENTRY_PATH_MAX_LENGTH,
    MANIFEST_LABEL_MAX_LENGTH,
    MANIFEST_MAX_ENTRIES,
    Entry,
    Extent,
    Manifest,
)
from keeper.custody.features.register_dataset_manifest.command import RegisterDatasetManifest
from keeper.custody.features.register_dataset_manifest.handler import Handler
from keeper.infrastructure.request import (
    ErrorResponse,
    get_correlation_id,
    get_principal_id,
    get_surface_id,
)
from keeper.shared.identifier import (
    IDENTIFIER_SCHEME_MAX_LENGTH,
    IDENTIFIER_VALUE_MAX_LENGTH,
    Identifier,
)


class ExternalRefBody(BaseModel):
    """The copy that was opened to produce this description."""

    scheme: str = Field(min_length=1, max_length=IDENTIFIER_SCHEME_MAX_LENGTH)
    value: str = Field(min_length=1, max_length=IDENTIFIER_VALUE_MAX_LENGTH)


class ExtentBody(BaseModel):
    """How much of something there is, and of what.

    Omitted whole when whatever described this did not measure it,
    which is ordinary rather than a defect: a store that serves
    structure of its own owns these numbers, and a reader asking that
    store sends the roles without them.
    """

    shape: list[int]
    capacity: list[int] | None = None
    dtype: str | None = Field(default=None, max_length=MANIFEST_LABEL_MAX_LENGTH)


class EntryBody(BaseModel):
    """One thing inside the container, and what a convention calls it.

    There is deliberately no field here for a number computed from the
    data. A description says whether something is worth opening and
    never answers instead of opening it.
    """

    path: str = Field(min_length=1, max_length=ENTRY_PATH_MAX_LENGTH)
    extent: ExtentBody | None = None
    role: str | None = Field(default=None, max_length=MANIFEST_LABEL_MAX_LENGTH)


class RegisterDatasetManifestRequest(BaseModel):
    """What was found inside, and which copy it was found in.

    `convention` names the vocabulary the roles are drawn from. A
    reader that understood the container and recognised nothing in it
    sends `unknown` with roles left out, which is a different answer
    from sending no description at all.

    `occurred_at` is optional and means when the container was read. A
    caller who omits it is saying nothing about when, and the honest
    answer to that is the moment the report arrived.
    """

    external_ref: ExternalRefBody
    convention: str = Field(min_length=1, max_length=MANIFEST_LABEL_MAX_LENGTH)
    entries: list[EntryBody] = Field(max_length=MANIFEST_MAX_ENTRIES)
    occurred_at: datetime | None = None


def _get_handler(request: Request) -> Handler:
    handler: Handler = request.app.state.custody.register_dataset_manifest
    return handler


def _extent(body: ExtentBody | None) -> Extent | None:
    if body is None:
        return None
    return Extent(
        shape=tuple(body.shape),
        capacity=None if body.capacity is None else tuple(body.capacity),
        dtype=body.dtype,
    )


router = APIRouter(tags=["custody"])


@router.post(
    "/datasets/{dataset_id}/manifests",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        status.HTTP_400_BAD_REQUEST: {
            "model": ErrorResponse,
            "description": (
                "The description is not well-formed, the external reference is not, "
                "or the reported timestamp carried no timezone."
            ),
        },
        status.HTTP_403_FORBIDDEN: {
            "model": ErrorResponse,
            "description": "The calling principal may not describe datasets.",
        },
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponse,
            "description": "The id names no dataset.",
        },
        status.HTTP_409_CONFLICT: {
            "model": ErrorResponse,
            "description": (
                "This dataset is not recorded at that address, or it already carries "
                "that same description of it."
            ),
        },
    },
    summary="Register what is inside a dataset",
)
async def post_dataset_manifests(
    dataset_id: UUID,
    body: RegisterDatasetManifestRequest,
    handler: Annotated[Handler, Depends(_get_handler)],
    cid: Annotated[UUID, Depends(get_correlation_id)],
    principal_id: Annotated[UUID, Depends(get_principal_id)],
    surface_id: Annotated[UUID, Depends(get_surface_id)],
) -> None:
    await handler(
        RegisterDatasetManifest(
            dataset_id=dataset_id,
            external_ref=Identifier(scheme=body.external_ref.scheme, value=body.external_ref.value),
            manifest=Manifest(
                convention=body.convention,
                entries=tuple(
                    Entry(path=entry.path, extent=_extent(entry.extent), role=entry.role)
                    for entry in body.entries
                ),
            ),
            occurred_at=body.occurred_at,
        ),
        principal_id=principal_id,
        correlation_id=cid,
        surface_id=surface_id,
    )
