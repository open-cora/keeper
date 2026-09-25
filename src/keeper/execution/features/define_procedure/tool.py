"""MCP door for defining a procedure.

The same handler the HTTP route uses. The handler is fetched per call
rather than at registration, so it sees the bundle the lifespan wired
rather than whatever existed when the server was built.

The step models are declared again here rather than imported from the
route, which is what every other slice in this context does. The two
surfaces share a handler and not a boundary: one parses a JSON body and
the other a tool call, and a tool importing a FastAPI request model
would make the MCP schema a function of how the HTTP one happened to be
written.

No idempotency key. MCP has no client-supplied retry tag to carry one,
so the wrapped handler is called with None and behaves as the bare one.
"""

from collections.abc import Callable
from typing import Annotated, Any, Literal
from uuid import UUID

from mcp.server.fastmcp import Context, FastMCP
from pydantic import BaseModel, Field

from keeper.execution.aggregates.procedure import (
    PROCEDURE_BEAMLINE_MAX_LENGTH,
    PROCEDURE_MAX_SCOPES_PER_STEP,
    PROCEDURE_MAX_STEPS,
    PROCEDURE_SCOPE_MAX_LENGTH,
    AcquireStep,
    MoveStep,
    ProcedureStep,
)
from keeper.execution.features.define_procedure.command import DefineProcedure
from keeper.execution.features.define_procedure.handler import IdempotentHandler
from keeper.infrastructure.observability import current_correlation_id
from keeper.infrastructure.request import get_mcp_surface_id
from keeper.infrastructure.slices.principal import get_mcp_principal_id


class MoveStepInput(BaseModel):
    """Send one record to one value."""

    kind: Literal["move"]
    record: str
    to: float


class AcquireStepInput(BaseModel):
    """Ask an engine to run a plan, over the devices this step declares."""

    kind: Literal["acquire"]
    plan_id: UUID
    parameters: dict[str, Any] = Field(default_factory=dict[str, Any])
    scopes: list[Annotated[str, Field(max_length=PROCEDURE_SCOPE_MAX_LENGTH)]] = Field(
        min_length=1, max_length=PROCEDURE_MAX_SCOPES_PER_STEP
    )


StepInput = Annotated[MoveStepInput | AcquireStepInput, Field(discriminator="kind")]


class DefineProcedureOutput(BaseModel):
    """What the tool hands back."""

    procedure_id: UUID


def _to_step(step: MoveStepInput | AcquireStepInput) -> ProcedureStep:
    """Turn one parsed tool step into the step the domain holds."""
    if isinstance(step, MoveStepInput):
        return MoveStep(record=step.record, to=step.to)
    return AcquireStep(
        plan_id=step.plan_id,
        parameters=step.parameters,
        scopes=tuple(step.scopes),
    )


def register(mcp: FastMCP, *, get_handler: Callable[[], IdempotentHandler]) -> None:
    """Register the tool on the given MCP server."""

    @mcp.tool(
        name="define_procedure",
        description=(
            "Compose a routine out of ordered steps and return its id. A move "
            "sends one record to one value; an acquisition runs a plan and must "
            "declare the devices it touches. The beamline says where the routine "
            "runs, which is what routes a dispatch of it to a conductor."
        ),
    )
    async def define_procedure_tool(  # pyright: ignore[reportUnusedFunction]
        ctx: Context[Any, Any, Any],
        name: str,
        beamline: Annotated[str, Field(max_length=PROCEDURE_BEAMLINE_MAX_LENGTH)],
        steps: Annotated[list[StepInput], Field(min_length=1, max_length=PROCEDURE_MAX_STEPS)],
    ) -> DefineProcedureOutput:
        handler = get_handler()
        procedure_id = await handler(
            DefineProcedure(
                name=name,
                beamline=beamline,
                steps=tuple(_to_step(step) for step in steps),
            ),
            principal_id=get_mcp_principal_id(ctx),
            # The tool runs inside the instrumented request that carried
            # it, so the trace context is already in scope.
            correlation_id=current_correlation_id(),
            surface_id=get_mcp_surface_id(),
        )
        return DefineProcedureOutput(procedure_id=procedure_id)
