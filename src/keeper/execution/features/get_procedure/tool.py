"""MCP door for reading a procedure.

The same handler the HTTP route uses, fetched per call so it sees the
bundle the lifespan wired rather than whatever existed at registration.

The step models are declared again here rather than imported from the
route, for the reason `define_procedure/tool.py` gives: the two surfaces
share a handler and not a boundary.
"""

from collections.abc import Callable
from typing import Annotated, Any, Literal
from uuid import UUID

from mcp.server.fastmcp import Context, FastMCP
from pydantic import BaseModel, Field

from keeper.execution.aggregates.procedure import ComposedStep, MoveStep
from keeper.execution.features.get_procedure.handler import Handler
from keeper.execution.features.get_procedure.query import GetProcedure
from keeper.infrastructure.observability import current_correlation_id
from keeper.infrastructure.request import get_mcp_surface_id
from keeper.infrastructure.slices.principal import get_mcp_principal_id


class MoveStepOutput(BaseModel):
    """A step that sends one record to one value."""

    kind: Literal["move"] = "move"
    step_id: UUID
    record: str
    to: float


class AcquireStepOutput(BaseModel):
    """A step that asks an engine to run a plan."""

    kind: Literal["acquire"] = "acquire"
    step_id: UUID
    plan_id: UUID
    parameters: dict[str, Any]
    scopes: list[str]


StepOutput = Annotated[MoveStepOutput | AcquireStepOutput, Field(discriminator="kind")]


class GetProcedureOutput(BaseModel):
    """A procedure as this system currently holds it."""

    procedure_id: UUID
    name: str
    beamline: str
    steps: list[StepOutput]


def _to_output_step(composed: ComposedStep) -> MoveStepOutput | AcquireStepOutput:
    """Render one stored step for a reader, under the id it was composed with.

    `step_id` is what an execution's step cites, so it is what a reader
    comparing a traversal against the routine it came from joins on.
    """
    step = composed.step
    if isinstance(step, MoveStep):
        return MoveStepOutput(step_id=composed.id, record=step.record, to=step.to)
    return AcquireStepOutput(
        step_id=composed.id,
        plan_id=step.plan_id,
        parameters=step.parameters,
        scopes=list(step.scopes),
    )


def register(mcp: FastMCP, *, get_handler: Callable[[], Handler]) -> None:
    """Register the tool on the given MCP server."""

    @mcp.tool(
        name="get_procedure",
        description=(
            "Read a procedure by id: the name it was composed under and every "
            "step it runs, in order."
        ),
    )
    async def get_procedure_tool(  # pyright: ignore[reportUnusedFunction]
        ctx: Context[Any, Any, Any],
        procedure_id: UUID,
    ) -> GetProcedureOutput:
        handler = get_handler()
        procedure = await handler(
            GetProcedure(procedure_id=procedure_id),
            principal_id=get_mcp_principal_id(ctx),
            # The tool runs inside the instrumented request that carried
            # it, so the trace context is already in scope.
            correlation_id=current_correlation_id(),
            surface_id=get_mcp_surface_id(),
        )
        return GetProcedureOutput(
            procedure_id=procedure.id,
            name=procedure.name.value,
            beamline=procedure.beamline.value,
            steps=[_to_output_step(composed) for composed in procedure.steps],
        )
