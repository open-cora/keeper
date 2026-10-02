"""HTTP door for withdrawing an address from a dataset.

`POST /datasets/{dataset_id}/addresses/withdraw`, carrying the address
that stopped answering.

**A POST with a body rather than a DELETE with path segments**, where
the nearest sibling in the tree revokes a permission with a DELETE. The
difference is what identifies the thing being removed. A permission is
named by two safe identifiers, and an address is named by a store's own
spelling, which routinely carries slashes, colons and spaces. Putting
one in a path means encoding it, and an encoded slash is the one piece
of URL handling that differs between every proxy in front of this.

A body also keeps the reference nested, which is what stops a caller
expressing half of one, and that is a rule this context already relies
on everywhere else it takes a reference.

`204`, because nothing is created and the caller already holds the
address it named.
"""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel, Field

from keeper.custody.features.withdraw_dataset_address.command import WithdrawDatasetAddress
from keeper.custody.features.withdraw_dataset_address.handler import Handler
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
    """The address that stopped answering."""

    scheme: str = Field(min_length=1, max_length=IDENTIFIER_SCHEME_MAX_LENGTH)
    value: str = Field(min_length=1, max_length=IDENTIFIER_VALUE_MAX_LENGTH)


class WithdrawDatasetAddressRequest(BaseModel):
    """The address to take off the record.

    `occurred_at` is optional and means when it stopped answering. A
    caller who omits it is saying nothing about when, and the honest
    answer to that is the moment the report arrived.
    """

    external_ref: ExternalRefBody
    occurred_at: datetime | None = None


def _get_handler(request: Request) -> Handler:
    handler: Handler = request.app.state.custody.withdraw_dataset_address
    return handler


router = APIRouter(tags=["custody"])


@router.post(
    "/datasets/{dataset_id}/addresses/withdraw",
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
            "description": "The calling principal may not withdraw dataset addresses.",
        },
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponse,
            "description": "The id names no dataset.",
        },
        status.HTTP_409_CONFLICT: {
            "model": ErrorResponse,
            "description": "This dataset is not recorded at that address.",
        },
    },
    summary="Withdraw an address from a dataset",
)
async def post_dataset_address_withdrawal(
    dataset_id: UUID,
    body: WithdrawDatasetAddressRequest,
    handler: Annotated[Handler, Depends(_get_handler)],
    cid: Annotated[UUID, Depends(get_correlation_id)],
    principal_id: Annotated[UUID, Depends(get_principal_id)],
    surface_id: Annotated[UUID, Depends(get_surface_id)],
) -> None:
    await handler(
        WithdrawDatasetAddress(
            dataset_id=dataset_id,
            external_ref=Identifier(scheme=body.external_ref.scheme, value=body.external_ref.value),
            occurred_at=body.occurred_at,
        ),
        principal_id=principal_id,
        correlation_id=cid,
        surface_id=surface_id,
    )
