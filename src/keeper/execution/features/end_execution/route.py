"""HTTP door for ending an execution.

`POST /executions/{execution_id}/end`, with an optional body. A verb in the path
rather than a PATCH setting a field, which is the shape the run's three
endings take and for the same reason: this names a transition the domain
either allows or refuses, where a PATCH would invite a caller to set any
state from any other.
"""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Request, status
from pydantic import BaseModel

from keeper.execution.features.end_execution.command import EndExecution
from keeper.execution.features.end_execution.handler import Handler
from keeper.infrastructure.request import (
    ErrorResponse,
    get_correlation_id,
    get_principal_id,
    get_surface_id,
)


def _get_handler(request: Request) -> Handler:
    handler: Handler = request.app.state.execution.end_execution
    return handler


class EndExecutionRequest(BaseModel):
    """When the execution ended, if the caller knows.

    The whole body, and the whole body is optional. Omitting it means
    the event is stamped with the moment the report arrived.
    """

    occurred_at: datetime | None = None


router = APIRouter(tags=["execution"])


@router.post(
    "/executions/{execution_id}/end",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        status.HTTP_400_BAD_REQUEST: {
            "model": ErrorResponse,
            "description": "The supplied occurred_at carried no timezone.",
        },
        status.HTTP_403_FORBIDDEN: {
            "model": ErrorResponse,
            "description": "The calling principal may not end executions.",
        },
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponse,
            "description": "No execution has that id.",
        },
        status.HTTP_409_CONFLICT: {
            "model": ErrorResponse,
            "description": "The execution has already ended, or was changed concurrently.",
        },
    },
    summary="End an execution",
)
async def post_execution_end(
    execution_id: UUID,
    handler: Annotated[Handler, Depends(_get_handler)],
    cid: Annotated[UUID, Depends(get_correlation_id)],
    principal_id: Annotated[UUID, Depends(get_principal_id)],
    surface_id: Annotated[UUID, Depends(get_surface_id)],
    body: Annotated[EndExecutionRequest | None, Body()] = None,
) -> None:
    await handler(
        EndExecution(execution_id=execution_id, occurred_at=body.occurred_at if body else None),
        principal_id=principal_id,
        correlation_id=cid,
        surface_id=surface_id,
    )
