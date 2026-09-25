"""HTTP door for defining a plan.

`POST /plans`, carrying the name the engine knows the routine by
and the schema its parameters must satisfy.

The length bound on the name is declared here as well as in the value
object, and the duplication is on purpose. This one turns an over-long
name into FastAPI's standard 422 alongside every other malformed-body
complaint, before a command is ever built. The one in the value object is
what holds for the MCP surface and for any caller that reaches the
decider another way. Neither is redundant, because neither covers the
other's callers.
"""

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request, status
from pydantic import BaseModel, Field

from keeper.execution.aggregates.plan import PLAN_NAME_MAX_LENGTH
from keeper.execution.features.define_plan.command import DefinePlan
from keeper.execution.features.define_plan.handler import IdempotentHandler
from keeper.infrastructure.request import (
    ErrorResponse,
    get_correlation_id,
    get_principal_id,
    get_surface_id,
)


class DefinePlanRequest(BaseModel):
    """The routine to write down, and the shape of its parameters.

    `parameters_schema` is required, with no default. A plan whose
    parameters nobody has described is the state the aggregate exists to
    refuse, and obtaining it by leaving a key out of the body would make
    the refusal look like a bug in the client.
    """

    name: str = Field(min_length=1, max_length=PLAN_NAME_MAX_LENGTH)
    parameters_schema: dict[str, Any]


class DefinePlanResponse(BaseModel):
    """The id of the plan that was created."""

    plan_id: UUID


def _get_handler(request: Request) -> IdempotentHandler:
    handler: IdempotentHandler = request.app.state.execution.define_plan
    return handler


router = APIRouter(tags=["execution"])


@router.post(
    "/plans",
    status_code=status.HTTP_201_CREATED,
    response_model=DefinePlanResponse,
    responses={
        status.HTTP_400_BAD_REQUEST: {
            "model": ErrorResponse,
            "description": "The name or the parameters schema is not well-formed.",
        },
        status.HTTP_403_FORBIDDEN: {
            "model": ErrorResponse,
            "description": "The calling principal may not define plans.",
        },
    },
    summary="Define a plan",
)
async def post_plans(
    body: DefinePlanRequest,
    handler: Annotated[IdempotentHandler, Depends(_get_handler)],
    cid: Annotated[UUID, Depends(get_correlation_id)],
    principal_id: Annotated[UUID, Depends(get_principal_id)],
    surface_id: Annotated[UUID, Depends(get_surface_id)],
    idempotency_key: Annotated[
        str | None,
        Header(
            alias="Idempotency-Key",
            description="Replay the same key to get the same plan back, not a second one.",
        ),
    ] = None,
) -> DefinePlanResponse:
    plan_id = await handler(
        DefinePlan(name=body.name, parameters_schema=body.parameters_schema),
        principal_id=principal_id,
        correlation_id=cid,
        surface_id=surface_id,
        idempotency_key=idempotency_key,
    )
    return DefinePlanResponse(plan_id=plan_id)
