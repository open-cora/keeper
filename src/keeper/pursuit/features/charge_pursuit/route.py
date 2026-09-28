"""HTTP door for charging a pursuit.

`POST /pursuits/{pursuit_id}/charges`, carrying a dimension, an amount and
the moment it was consumed.

A POST to a collection rather than to a verb subresource, because each
call adds one charge to a list rather than transitioning the pursuit. That
is also why this one is a 201 where withdrawing is a 204: something was
created.

`occurred_at` is optional and is the caller's when given. What this
records happened somewhere else, so the caller is the one that knows when,
and the clock here is only the fallback for a reporter with nothing better.
A value carrying no timezone is a 400 from the shared helper, which
Execution registers for the whole application.

The `Idempotency-Key` header is the one in this context that does
something. Charges add rather than replace, so a redelivered one spends
the budget twice on a record that cannot be edited.
"""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request, status
from pydantic import BaseModel, Field

from keeper.infrastructure.request import (
    ErrorResponse,
    get_correlation_id,
    get_principal_id,
    get_surface_id,
)
from keeper.pursuit.aggregates.pursuit import BudgetDimension
from keeper.pursuit.features.charge_pursuit.command import ChargePursuit
from keeper.pursuit.features.charge_pursuit.handler import IdempotentHandler


class ChargePursuitRequest(BaseModel):
    """What was consumed, how much of it, and when."""

    dimension: BudgetDimension = Field(
        description=(
            "Which resource was consumed. Only BeamSeconds and Tokens may be "
            "reported; the rest are counted from the record itself."
        )
    )
    amount: int = Field(gt=0, description="How much, added to what the pursuit has spent.")
    occurred_at: datetime | None = Field(
        default=None,
        description="When it was consumed, if the caller knows. Defaults to now.",
    )


class ChargePursuitResponse(BaseModel):
    """Where the pursuit now stands in the dimension that was charged."""

    pursuit_id: UUID
    dimension: BudgetDimension
    total: int = Field(description="Everything charged in this dimension, including this call.")


def _get_handler(request: Request) -> IdempotentHandler:
    handler: IdempotentHandler = request.app.state.pursuit.charge_pursuit
    return handler


router = APIRouter(tags=["pursuit"])


@router.post(
    "/pursuits/{pursuit_id}/charges",
    status_code=status.HTTP_201_CREATED,
    response_model=ChargePursuitResponse,
    responses={
        status.HTTP_400_BAD_REQUEST: {
            "model": ErrorResponse,
            "description": (
                "The amount is not positive, the dimension is one this system "
                "counts for itself, or the pursuit was never bounded in it."
            ),
        },
        status.HTTP_403_FORBIDDEN: {
            "model": ErrorResponse,
            "description": "The calling principal may not charge pursuits.",
        },
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponse,
            "description": "No pursuit with that id.",
        },
    },
    summary="Charge a pursuit",
)
async def post_pursuit_charge(
    pursuit_id: UUID,
    body: ChargePursuitRequest,
    handler: Annotated[IdempotentHandler, Depends(_get_handler)],
    cid: Annotated[UUID, Depends(get_correlation_id)],
    principal_id: Annotated[UUID, Depends(get_principal_id)],
    surface_id: Annotated[UUID, Depends(get_surface_id)],
    idempotency_key: Annotated[
        str | None,
        Header(
            alias="Idempotency-Key",
            description="Replay the same key to add the charge once, not twice.",
        ),
    ] = None,
) -> ChargePursuitResponse:
    total = await handler(
        ChargePursuit(
            pursuit_id=pursuit_id,
            dimension=body.dimension,
            amount=body.amount,
            occurred_at=body.occurred_at,
        ),
        principal_id=principal_id,
        correlation_id=cid,
        surface_id=surface_id,
        idempotency_key=idempotency_key,
    )
    return ChargePursuitResponse(pursuit_id=pursuit_id, dimension=body.dimension, total=total)
