"""HTTP door for reading a plan.

`GET /plans/{plan_id}`. Returns the id, the name, and the schema the
plan's parameters must satisfy, which is the whole of what a plan is.

The schema goes back exactly as it was stored, not re-rendered. A caller
generating a form or validating a request locally has to be validating
against the same document this system will validate against, and any
normalisation on the way out is a chance for the two to differ.

The state is folded from the stream on every call. A plan is one row
today, so a summary table would be machinery maintained ahead of a need.
That changes when plans are listed rather than fetched by id, which is
the query a fold cannot serve.
"""

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel

from keeper.execution.features.get_plan.handler import Handler
from keeper.execution.features.get_plan.query import GetPlan
from keeper.infrastructure.request import (
    ErrorResponse,
    get_correlation_id,
    get_principal_id,
    get_surface_id,
)


class GetPlanResponse(BaseModel):
    """A plan as this system currently holds it."""

    plan_id: UUID
    name: str
    parameters_schema: dict[str, Any]


def _get_handler(request: Request) -> Handler:
    handler: Handler = request.app.state.execution.get_plan
    return handler


router = APIRouter(tags=["execution"])


@router.get(
    "/plans/{plan_id}",
    response_model=GetPlanResponse,
    responses={
        status.HTTP_403_FORBIDDEN: {
            "model": ErrorResponse,
            "description": "The calling principal may not read plans.",
        },
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponse,
            "description": "No plan has that id.",
        },
    },
    summary="Read a plan",
)
async def get_plan(
    plan_id: UUID,
    handler: Annotated[Handler, Depends(_get_handler)],
    cid: Annotated[UUID, Depends(get_correlation_id)],
    principal_id: Annotated[UUID, Depends(get_principal_id)],
    surface_id: Annotated[UUID, Depends(get_surface_id)],
) -> GetPlanResponse:
    plan = await handler(
        GetPlan(plan_id=plan_id),
        principal_id=principal_id,
        correlation_id=cid,
        surface_id=surface_id,
    )
    return GetPlanResponse(
        plan_id=plan.id,
        name=plan.name.value,
        parameters_schema=plan.parameters_schema,
    )
