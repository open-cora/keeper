"""HTTP door for relaying an engine's account of one step's run.

`POST /executions/{execution_id}/steps/{step_id}/run`, carrying what the engine
did.

A step in the path and a verb in the body, where every other transition
in this context puts the verb in the path. The difference is what the
caller is. A driver calls one endpoint per thing it means; a reporter
drains an engine's document stream and turns each document into whichever
of six this one is, so a path per verb would make it build a URL by
lookup where a field costs it nothing.

The step is addressed by id rather than by index, because whatever
watches an engine knows only the id a driver carried into that engine's
own metadata.
"""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel

from keeper.execution.aggregates.execution import EngineReport
from keeper.execution.features.report_step_run.command import ReportStepRun
from keeper.execution.features.report_step_run.handler import Handler
from keeper.infrastructure.request import (
    ErrorResponse,
    get_correlation_id,
    get_principal_id,
    get_surface_id,
)


def _get_handler(request: Request) -> Handler:
    handler: Handler = request.app.state.execution.report_step_run
    return handler


class ReportStepRunRequest(BaseModel):
    """What the engine did, and when.

    `engine_reference` belongs to a start. Sending it with any other
    report is accepted and ignored rather than refused, which is the one
    place this is laxer than the sibling slice: a reporter relaying a
    document stream repeats the engine's own uid on every document, and
    refusing that would make the common case an error.
    """

    reported: EngineReport
    engine_reference: str | None = None
    occurred_at: datetime | None = None


router = APIRouter(tags=["execution"])


@router.post(
    "/executions/{execution_id}/steps/{step_id}/run",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        status.HTTP_400_BAD_REQUEST: {
            "model": ErrorResponse,
            "description": "The supplied occurred_at carried no timezone.",
        },
        status.HTTP_403_FORBIDDEN: {
            "model": ErrorResponse,
            "description": "The calling principal may not report engine state.",
        },
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponse,
            "description": "No execution has that id, or it holds no such step.",
        },
        status.HTTP_409_CONFLICT: {
            "model": ErrorResponse,
            "description": "The report does not follow the engine state already recorded, "
            "or the execution changed between the read and the write.",
        },
    },
    summary="Report what an engine did to a step's run",
)
async def post_step_run(
    execution_id: UUID,
    step_id: UUID,
    body: ReportStepRunRequest,
    handler: Annotated[Handler, Depends(_get_handler)],
    cid: Annotated[UUID, Depends(get_correlation_id)],
    principal_id: Annotated[UUID, Depends(get_principal_id)],
    surface_id: Annotated[UUID, Depends(get_surface_id)],
) -> None:
    await handler(
        ReportStepRun(
            execution_id=execution_id,
            step_id=step_id,
            reported=body.reported,
            engine_reference=body.engine_reference,
            occurred_at=body.occurred_at,
        ),
        principal_id=principal_id,
        correlation_id=cid,
        surface_id=surface_id,
    )
