"""HTTP door for dispatching an execution.

`POST /executions`, carrying the procedure to hand out and nothing else.

The body is one field on purpose. The procedure already holds the steps,
their order and the devices each touches, so a caller that also supplied
a step list would be able to dispatch something other than what it
named, and this system would have no way to tell which it meant.

No `occurred_at`, unlike every other write on this stream. A dispatch
happens here, at the moment the record is written, so there is no
earlier instant to report. The step reports that follow do take one,
because those describe something that happened at a beamline.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request, status
from pydantic import BaseModel

from keeper.execution.features.dispatch_execution.command import DispatchExecution
from keeper.execution.features.dispatch_execution.handler import IdempotentHandler
from keeper.infrastructure.request import (
    ErrorResponse,
    get_correlation_id,
    get_principal_id,
    get_surface_id,
)


def _get_handler(request: Request) -> IdempotentHandler:
    handler: IdempotentHandler = request.app.state.execution.dispatch_execution
    return handler


class DispatchExecutionRequest(BaseModel):
    """The procedure to hand out."""

    procedure_id: UUID


class DispatchExecutionResponse(BaseModel):
    """The id of the execution that was created."""

    execution_id: UUID


router = APIRouter(tags=["execution"])


@router.post(
    "/executions",
    status_code=status.HTTP_201_CREATED,
    response_model=DispatchExecutionResponse,
    responses={
        status.HTTP_400_BAD_REQUEST: {
            "model": ErrorResponse,
            "description": "The procedure's name or steps fall outside what an execution stores.",
        },
        status.HTTP_403_FORBIDDEN: {
            "model": ErrorResponse,
            "description": "The calling principal may not dispatch executions.",
        },
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponse,
            "description": "No procedure has that id.",
        },
    },
    summary="Dispatch an execution",
)
async def post_executions(
    body: DispatchExecutionRequest,
    handler: Annotated[IdempotentHandler, Depends(_get_handler)],
    cid: Annotated[UUID, Depends(get_correlation_id)],
    principal_id: Annotated[UUID, Depends(get_principal_id)],
    surface_id: Annotated[UUID, Depends(get_surface_id)],
    idempotency_key: Annotated[
        str | None,
        Header(
            alias="Idempotency-Key",
            description="Replay the same key to get the same execution back, not a second one.",
        ),
    ] = None,
) -> DispatchExecutionResponse:
    execution_id = await handler(
        DispatchExecution(procedure_id=body.procedure_id),
        principal_id=principal_id,
        correlation_id=cid,
        surface_id=surface_id,
        idempotency_key=idempotency_key,
    )
    return DispatchExecutionResponse(execution_id=execution_id)
