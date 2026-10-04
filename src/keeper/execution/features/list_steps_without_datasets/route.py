"""HTTP door for listing runs whose output nothing recorded.

`GET /steps/without-datasets`, newest first, optionally narrowed to one
beamline.

A path of its own rather than a flag on the execution listing. The rows
are steps and not executions, and a query parameter that changed what a
route returns row-for-row would be two endpoints sharing a URL.

## What a row here means, and what it does not

It means the record is incomplete, not that data was lost. The step
ran, the engine wrote its output, and the reference in the row is what
the engine called it. What is missing is any record of where that
output is being kept, which is a thing that can be supplied later
without re-running anything.

The usual cause is a beamline where neither of the two programs that
could file was in a position to. A driver files when its engine hands
back a location; a reporter files when a store can resolve a name.
Neither knows about the other, on purpose, so a deployment with neither
is one nothing refuses at startup and this is where it shows up.

## Why it is not a count

A number would say how bad it is and nothing about what to do. Each row
carries the sentence the step was dispatched with and the engine's own
reference, which together are what somebody needs to find the data and
file it by hand.
"""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status
from pydantic import BaseModel

from keeper.execution.aggregates.execution import ExecutionBeamline
from keeper.execution.features.list_steps_without_datasets.handler import Handler
from keeper.execution.features.list_steps_without_datasets.query import (
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    ListStepsWithoutDatasets,
)
from keeper.infrastructure.request import (
    ErrorResponse,
    get_correlation_id,
    get_principal_id,
    get_surface_id,
)


def _get_handler(request: Request) -> Handler:
    handler: Handler = request.app.state.execution.list_steps_without_datasets
    return handler


class UnfiledStepResponse(BaseModel):
    """One run whose output nothing recorded.

    `describes` is the sentence the step was dispatched with, so a
    reader can tell which piece of work the missing data belongs to
    without fetching the execution.

    `engine_reference` is what the engine called the run. At a beamline
    whose engine answers with a location it is the path the data was
    written to, and filing the dataset by hand needs nothing else.

    `run_opened_at` is what separates the two faults this listing
    returns, and reading it is the difference between fixing one run
    and fixing a beamline. A time means something watched this run
    begin and its data went unrecorded anyway, so the engine or the
    filing failed and the loss is one run. None means nothing was
    watching, so no run at that beamline is being recorded and the
    reporter there is down or was never installed.
    """

    step_id: UUID
    execution_id: UUID
    index: int
    describes: str
    beamline: str
    outcome: str | None
    engine_reference: str | None
    reported_at: datetime | None
    run_opened_at: datetime | None


class ListStepsWithoutDatasetsResponse(BaseModel):
    """One page, and the cursor that continues it."""

    items: list[UnfiledStepResponse]
    next_cursor: str | None


router = APIRouter(tags=["execution"])


@router.get(
    "/steps/without-datasets",
    response_model=ListStepsWithoutDatasetsResponse,
    responses={
        status.HTTP_400_BAD_REQUEST: {
            "model": ErrorResponse,
            "description": "The cursor was not well-formed.",
        },
        status.HTTP_403_FORBIDDEN: {
            "model": ErrorResponse,
            "description": "The calling principal may not read the custody gap.",
        },
        status.HTTP_422_UNPROCESSABLE_CONTENT: {
            "model": ErrorResponse,
            "description": "The cursor did not come from a previous response.",
        },
    },
    summary="List runs whose data was never registered",
)
async def list_steps_without_datasets(
    handler: Annotated[Handler, Depends(_get_handler)],
    cid: Annotated[UUID, Depends(get_correlation_id)],
    principal_id: Annotated[UUID, Depends(get_principal_id)],
    surface_id: Annotated[UUID, Depends(get_surface_id)],
    beamline: Annotated[
        str | None,
        Query(
            description="Only the gaps at this beamline, such as 2-bm. "
            "Omit it to see the whole facility's.",
        ),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
    cursor: Annotated[str | None, Query()] = None,
) -> ListStepsWithoutDatasetsResponse:
    page = await handler(
        ListStepsWithoutDatasets(
            beamline=ExecutionBeamline(beamline) if beamline is not None else None,
            limit=limit,
            cursor=cursor,
        ),
        principal_id=principal_id,
        correlation_id=cid,
        surface_id=surface_id,
    )

    return ListStepsWithoutDatasetsResponse(
        items=[
            UnfiledStepResponse(
                step_id=summary.step_id,
                execution_id=summary.execution_id,
                index=summary.index,
                describes=summary.describes,
                beamline=summary.beamline.value,
                outcome=summary.outcome,
                engine_reference=summary.engine_reference,
                reported_at=summary.reported_at,
                run_opened_at=summary.run_opened_at,
            )
            for summary in page.items
        ],
        next_cursor=page.next_cursor,
    )
