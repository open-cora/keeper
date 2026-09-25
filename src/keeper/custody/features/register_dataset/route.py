"""HTTP door for registering a dataset.

`POST /datasets`, carrying the run that produced the data and what the
store holding it calls the result.

A POST that creates a record of something that already exists elsewhere,
not a POST that writes any data. The resource being created is the
record. Nothing here reaches the store, and nothing here could: a caller
that can see the data is the one that knows its address.

`external_ref` is nested rather than flattened into two top-level keys,
so the body cannot express half a reference and the shape matches the
value object it becomes. The bounds on its two strings are declared here
as well as on that value object: this one turns an over-long scheme into
FastAPI's standard 422 before a command exists, and the value object is
what holds for the MCP surface and for any caller that reaches the
decider another way.
"""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request, status
from pydantic import BaseModel, Field

from keeper.custody.features.register_dataset.command import RegisterDataset
from keeper.custody.features.register_dataset.handler import IdempotentHandler
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
    """What the store holding this data calls it.

    `scheme` names the store's own addressing vocabulary. It is open on
    purpose: which store a deployment keeps its data in is a deployment's
    fact, not something this system should hold a list of.

    `value` is stored exactly as it arrives, trimmed and no more. A store
    that can spell one address two ways will make two records unless the
    caller settles on one first, and settling is the caller's because how
    an address is spelled is the store's fact rather than this system's.
    """

    scheme: str = Field(min_length=1, max_length=IDENTIFIER_SCHEME_MAX_LENGTH)
    value: str = Field(min_length=1, max_length=IDENTIFIER_VALUE_MAX_LENGTH)


class RegisterDatasetRequest(BaseModel):
    """The dataset to write down.

    `occurred_at` is optional and means when the data was written. A
    caller who omits it is saying nothing about when, and the honest
    answer to that is the moment the report arrived.
    """

    execution_id: UUID
    step_id: UUID
    external_ref: ExternalRefBody
    occurred_at: datetime | None = None


class RegisterDatasetResponse(BaseModel):
    """The id of the dataset record that was created."""

    dataset_id: UUID


def _get_handler(request: Request) -> IdempotentHandler:
    handler: IdempotentHandler = request.app.state.custody.register_dataset
    return handler


router = APIRouter(tags=["custody"])


@router.post(
    "/datasets",
    status_code=status.HTTP_201_CREATED,
    response_model=RegisterDatasetResponse,
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
            "description": "The calling principal may not register datasets.",
        },
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponse,
            "description": "No run has that id.",
        },
    },
    summary="Register a dataset",
)
async def post_datasets(
    body: RegisterDatasetRequest,
    handler: Annotated[IdempotentHandler, Depends(_get_handler)],
    cid: Annotated[UUID, Depends(get_correlation_id)],
    principal_id: Annotated[UUID, Depends(get_principal_id)],
    surface_id: Annotated[UUID, Depends(get_surface_id)],
    idempotency_key: Annotated[
        str | None,
        Header(
            alias="Idempotency-Key",
            description=("Replay the same key to get the same dataset back, not a second one."),
        ),
    ] = None,
) -> RegisterDatasetResponse:
    dataset_id = await handler(
        RegisterDataset(
            execution_id=body.execution_id,
            step_id=body.step_id,
            external_ref=Identifier(scheme=body.external_ref.scheme, value=body.external_ref.value),
            occurred_at=body.occurred_at,
        ),
        principal_id=principal_id,
        correlation_id=cid,
        surface_id=surface_id,
        idempotency_key=idempotency_key,
    )
    return RegisterDatasetResponse(dataset_id=dataset_id)
