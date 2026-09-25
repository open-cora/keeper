"""HTTP door for defining a procedure.

`POST /procedures`, carrying the name this system will know the routine
by and the ordered steps it is made of.

The bounds are declared here as well as in the aggregate, and the
duplication is on purpose. These turn a malformed body into FastAPI's
standard 422 alongside every other structural complaint, before a command
is ever built. The ones in the aggregate are what hold for the MCP
surface and for any caller that reaches the decider another way. Neither
is redundant, because neither covers the other's callers.

The step union is discriminated on `kind`, so a body naming a kind this
version does not know is refused by the request model with a message
saying which kinds there are, rather than reaching the domain as a step
with nothing in it.
"""

from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request, status
from pydantic import BaseModel, Field

from keeper.execution.aggregates.procedure import (
    PROCEDURE_BEAMLINE_MAX_LENGTH,
    PROCEDURE_MAX_SCOPES_PER_STEP,
    PROCEDURE_MAX_STEPS,
    PROCEDURE_NAME_MAX_LENGTH,
    PROCEDURE_RECORD_MAX_LENGTH,
    PROCEDURE_SCOPE_MAX_LENGTH,
    AcquireStep,
    MoveStep,
    ProcedureStep,
)
from keeper.execution.features.define_procedure.command import DefineProcedure
from keeper.execution.features.define_procedure.handler import IdempotentHandler
from keeper.infrastructure.request import (
    ErrorResponse,
    get_correlation_id,
    get_principal_id,
    get_surface_id,
)


class MoveStepRequest(BaseModel):
    """Send one record to one value.

    No scopes. What a move touches is the record it names, and whatever
    drives the procedure derives the claim from that.
    """

    kind: Literal["move"]
    record: str = Field(min_length=1, max_length=PROCEDURE_RECORD_MAX_LENGTH)
    to: float


class AcquireStepRequest(BaseModel):
    """Ask an engine to run a plan, over the devices this step declares.

    `scopes` is required and must name at least one device. Nothing here
    can look inside a routine to work out what it will drive, so a step
    that declared nothing would be one this system believes touches no
    hardware.
    """

    kind: Literal["acquire"]
    plan_id: UUID
    parameters: dict[str, Any] = Field(default_factory=dict[str, Any])
    scopes: list[Annotated[str, Field(min_length=1, max_length=PROCEDURE_SCOPE_MAX_LENGTH)]] = (
        Field(min_length=1, max_length=PROCEDURE_MAX_SCOPES_PER_STEP)
    )


StepRequest = Annotated[MoveStepRequest | AcquireStepRequest, Field(discriminator="kind")]


class DefineProcedureRequest(BaseModel):
    """The routine to compose, where it runs, and the steps it runs in order."""

    name: str = Field(min_length=1, max_length=PROCEDURE_NAME_MAX_LENGTH)
    beamline: str = Field(
        min_length=1,
        max_length=PROCEDURE_BEAMLINE_MAX_LENGTH,
        description="Which beamline this routine is composed for, such as 2-bm. "
        "A dispatch of it is routed to the conductor configured with the same word.",
    )
    steps: list[StepRequest] = Field(min_length=1, max_length=PROCEDURE_MAX_STEPS)


class DefineProcedureResponse(BaseModel):
    """The id of the procedure that was created."""

    procedure_id: UUID


def to_step(body: MoveStepRequest | AcquireStepRequest) -> ProcedureStep:
    """Turn one parsed request step into the step the domain holds."""
    if isinstance(body, MoveStepRequest):
        return MoveStep(record=body.record, to=body.to)
    return AcquireStep(
        plan_id=body.plan_id,
        parameters=body.parameters,
        scopes=tuple(body.scopes),
    )


def _get_handler(request: Request) -> IdempotentHandler:
    handler: IdempotentHandler = request.app.state.execution.define_procedure
    return handler


router = APIRouter(tags=["execution"])


@router.post(
    "/procedures",
    status_code=status.HTTP_201_CREATED,
    response_model=DefineProcedureResponse,
    responses={
        status.HTTP_400_BAD_REQUEST: {
            "model": ErrorResponse,
            "description": "The name, the beamline, the steps, or an acquisition's "
            "parameters are not well-formed.",
        },
        status.HTTP_403_FORBIDDEN: {
            "model": ErrorResponse,
            "description": "The calling principal may not define procedures.",
        },
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponse,
            "description": "An acquisition cites a plan that does not exist.",
        },
    },
    summary="Define a procedure",
)
async def post_procedures(
    body: DefineProcedureRequest,
    handler: Annotated[IdempotentHandler, Depends(_get_handler)],
    cid: Annotated[UUID, Depends(get_correlation_id)],
    principal_id: Annotated[UUID, Depends(get_principal_id)],
    surface_id: Annotated[UUID, Depends(get_surface_id)],
    idempotency_key: Annotated[
        str | None,
        Header(
            alias="Idempotency-Key",
            description="Replay the same key to get the same procedure back, not a second one.",
        ),
    ] = None,
) -> DefineProcedureResponse:
    procedure_id = await handler(
        DefineProcedure(
            name=body.name,
            beamline=body.beamline,
            steps=tuple(to_step(step) for step in body.steps),
        ),
        principal_id=principal_id,
        correlation_id=cid,
        surface_id=surface_id,
        idempotency_key=idempotency_key,
    )
    return DefineProcedureResponse(procedure_id=procedure_id)
