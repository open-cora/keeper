"""HTTP door for recording a finding about a dataset.

`POST /datasets/{dataset_id}/findings`, carrying what was concluded and
the two counts it was concluded from.

A collection, like the manifests and the addresses beside it, because a
dataset carries as many findings as there are things somebody looked
at. What the record folds to is one per judgement, which is a reading
of the history rather than a thing this surface promises.

`204`, because a finding has no id of its own. It is identified by the
dataset and the judgement, both of which the caller already holds.

The body is flat, where the manifest beside it nests. A manifest
carries a list whose members each have an extent, so nesting is what
keeps an entry from being half given. A finding is three scalars that
mean nothing apart, and a nested object around them would be a shape a
caller has to assemble for no refusal it buys.

The bounds on the judgement are declared here as well as on the value
object: this turns an over-long word into FastAPI's standard 422 before
a command exists, and the value object is what holds for the MCP
surface and for anything replaying the log.
"""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel, Field

from keeper.custody.aggregates.dataset import FINDING_JUDGEMENT_MAX_LENGTH, Finding
from keeper.custody.features.record_dataset_finding.command import RecordDatasetFinding
from keeper.custody.features.record_dataset_finding.handler import Handler
from keeper.infrastructure.request import (
    ErrorResponse,
    get_correlation_id,
    get_principal_id,
    get_surface_id,
)


class RecordDatasetFindingRequest(BaseModel):
    """What was concluded about this data, and the counts behind it.

    `judgement` is the word the computation reached for, and nothing
    here checks it against a list. A vocabulary this system defined
    would stop at the cases it thought of first.

    `expected` and `arrived` are what the computation expected to find
    and what it found. Presence counts: a thing that should be there
    and is not is one against zero.

    There is deliberately no field for a value read out of the data. A
    finding says what was concluded and never enough to let a reader
    recompute it from numbers it was handed here.

    `occurred_at` is optional and means when the conclusion was
    reached. A caller who omits it is saying nothing about when, and
    the honest answer to that is the moment the report arrived.
    """

    judgement: str = Field(min_length=1, max_length=FINDING_JUDGEMENT_MAX_LENGTH)
    expected: int = Field(ge=0)
    arrived: int = Field(ge=0)
    occurred_at: datetime | None = None


def _get_handler(request: Request) -> Handler:
    handler: Handler = request.app.state.custody.record_dataset_finding
    return handler


router = APIRouter(tags=["custody"])


@router.post(
    "/datasets/{dataset_id}/findings",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        status.HTTP_400_BAD_REQUEST: {
            "model": ErrorResponse,
            "description": (
                "The finding is not well-formed, or the reported timestamp carried no timezone."
            ),
        },
        status.HTTP_403_FORBIDDEN: {
            "model": ErrorResponse,
            "description": "The calling principal may not record findings.",
        },
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponse,
            "description": "The id names no dataset.",
        },
        status.HTTP_409_CONFLICT: {
            "model": ErrorResponse,
            "description": (
                "This dataset already carries that same finding, or it already carries "
                "as many distinct judgements as it may."
            ),
        },
    },
    summary="Record what somebody concluded about a dataset",
)
async def post_dataset_findings(
    dataset_id: UUID,
    body: RecordDatasetFindingRequest,
    handler: Annotated[Handler, Depends(_get_handler)],
    cid: Annotated[UUID, Depends(get_correlation_id)],
    principal_id: Annotated[UUID, Depends(get_principal_id)],
    surface_id: Annotated[UUID, Depends(get_surface_id)],
) -> None:
    await handler(
        RecordDatasetFinding(
            dataset_id=dataset_id,
            finding=Finding(
                judgement=body.judgement,
                expected=body.expected,
                arrived=body.arrived,
            ),
            occurred_at=body.occurred_at,
        ),
        principal_id=principal_id,
        correlation_id=cid,
        surface_id=surface_id,
    )
