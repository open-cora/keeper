"""HTTP door for registering another address for a dataset.

`POST /datasets/{dataset_id}/addresses`, carrying a place the data can
now be read and, when this system asked for the copy, the work that
made it.

A POST that creates a record of something that already exists
elsewhere, not a copy. Nothing here moves data and nothing here could:
whatever moved it is what knows the new address.

`204`, because an address has no id of its own. It is identified by its
scheme and value, which the caller already holds, so there is nothing
to hand back. That is the shape the nearest sibling in the tree uses,
where granting a permission also creates something the caller can name
without being told.

Both nested objects are nested rather than flattened into top-level
keys, so the body cannot express half a reference or half a citation.
The bounds on the reference's two strings are declared here as well as
on the value object: this one turns an over-long scheme into FastAPI's
standard 422 before a command exists, and the value object is what
holds for the MCP surface.
"""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel, Field

from keeper.custody.aggregates.dataset import CopiedBy
from keeper.custody.features.register_dataset_address.command import RegisterDatasetAddress
from keeper.custody.features.register_dataset_address.handler import Handler
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
    """A place the store holding this data answers to.

    `scheme` names the store's own addressing vocabulary and is open on
    purpose, for the reason the genesis route gives: which store a
    deployment keeps its data in is a deployment's fact.
    """

    scheme: str = Field(min_length=1, max_length=IDENTIFIER_SCHEME_MAX_LENGTH)
    value: str = Field(min_length=1, max_length=IDENTIFIER_VALUE_MAX_LENGTH)


class CopiedByBody(BaseModel):
    """The work that made this copy, when this system dispatched it.

    Omitted by a caller that copied data on its own account, which is
    most of them. Both halves are required together because half a
    citation names nothing.
    """

    execution_id: UUID
    step_id: UUID


class RegisterDatasetAddressRequest(BaseModel):
    """The address to write down.

    `occurred_at` is optional and means when the copy landed. A caller
    who omits it is saying nothing about when, and the honest answer to
    that is the moment the report arrived.
    """

    external_ref: ExternalRefBody
    copied_by: CopiedByBody | None = None
    occurred_at: datetime | None = None


def _get_handler(request: Request) -> Handler:
    handler: Handler = request.app.state.custody.register_dataset_address
    return handler


router = APIRouter(tags=["custody"])


@router.post(
    "/datasets/{dataset_id}/addresses",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        status.HTTP_400_BAD_REQUEST: {
            "model": ErrorResponse,
            "description": (
                "The external reference is not well-formed, or the reported "
                "timestamp carried no timezone."
            ),
        },
        status.HTTP_403_FORBIDDEN: {
            "model": ErrorResponse,
            "description": "The calling principal may not register dataset addresses.",
        },
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponse,
            "description": "The id names no dataset.",
        },
        status.HTTP_409_CONFLICT: {
            "model": ErrorResponse,
            "description": "This dataset is already recorded at that address.",
        },
    },
    summary="Register another address for a dataset",
)
async def post_dataset_addresses(
    dataset_id: UUID,
    body: RegisterDatasetAddressRequest,
    handler: Annotated[Handler, Depends(_get_handler)],
    cid: Annotated[UUID, Depends(get_correlation_id)],
    principal_id: Annotated[UUID, Depends(get_principal_id)],
    surface_id: Annotated[UUID, Depends(get_surface_id)],
) -> None:
    copied_by = body.copied_by
    await handler(
        RegisterDatasetAddress(
            dataset_id=dataset_id,
            external_ref=Identifier(scheme=body.external_ref.scheme, value=body.external_ref.value),
            copied_by=(
                None
                if copied_by is None
                else CopiedBy(execution_id=copied_by.execution_id, step_id=copied_by.step_id)
            ),
            occurred_at=body.occurred_at,
        ),
        principal_id=principal_id,
        correlation_id=cid,
        surface_id=surface_id,
    )
