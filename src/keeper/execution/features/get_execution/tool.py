"""MCP door for reading one execution.

The same handler the HTTP route uses. The handler is fetched per call
rather than at registration, so it sees the bundle the lifespan wired
rather than whatever existed when the server was built.
"""

from collections.abc import Callable
from typing import Any
from uuid import UUID

from mcp.server.fastmcp import Context, FastMCP
from pydantic import BaseModel

from keeper.execution.aggregates.execution import EngineState, ExecutionStatus, StepOutcome
from keeper.execution.features.get_execution.handler import Handler
from keeper.execution.features.get_execution.query import GetExecution
from keeper.infrastructure.observability import current_correlation_id
from keeper.infrastructure.request import get_mcp_surface_id
from keeper.infrastructure.slices.principal import get_mcp_principal_id


class ExecutionStepOutput(BaseModel):
    """One step, and whichever detail its outcome carried.

    `outcome` is null for a step nothing has reported yet, which is not
    the same as a step that was skipped.

    `procedure_step_id` names the composed step this one was dispatched
    from. Read the procedure to learn what the step was asked to do: the
    plan an acquisition hands to an engine, the parameters it carries and
    the devices it declares are all there, and none of them should be
    recovered by taking `describes` apart.
    """

    step_id: UUID
    describes: str
    procedure_step_id: UUID
    outcome: StepOutcome | None
    engine_reference: str | None
    engine_state: EngineState | None
    cause: str | None


class GetExecutionOutput(BaseModel):
    """An execution as a reader sees it, steps and all."""

    execution_id: UUID
    procedure_id: UUID
    procedure_name: str
    beamline: str
    status: ExecutionStatus
    steps: list[ExecutionStepOutput]


def register(mcp: FastMCP, *, get_handler: Callable[[], Handler]) -> None:
    """Register the tool on the given MCP server."""

    @mcp.tool(
        name="get_execution",
        description="Read one execution and how each of its steps ended.",
    )
    async def get_execution_tool(  # pyright: ignore[reportUnusedFunction]
        ctx: Context[Any, Any, Any],
        execution_id: UUID,
    ) -> GetExecutionOutput:
        handler = get_handler()
        execution = await handler(
            GetExecution(execution_id=execution_id),
            principal_id=get_mcp_principal_id(ctx),
            # The tool runs inside the instrumented request that carried
            # it, so the trace context is already in scope.
            correlation_id=current_correlation_id(),
            surface_id=get_mcp_surface_id(),
        )
        return GetExecutionOutput(
            execution_id=execution.id,
            procedure_id=execution.procedure_id,
            procedure_name=execution.procedure_name.value,
            beamline=execution.beamline.value,
            status=execution.status,
            steps=[
                ExecutionStepOutput(
                    step_id=step.id,
                    describes=step.describes,
                    procedure_step_id=step.procedure_step_id,
                    outcome=step.outcome,
                    engine_reference=step.engine_reference,
                    engine_state=step.engine_state,
                    cause=step.cause,
                )
                for step in execution.steps
            ],
        )
