"""MCP door for reading a plan.

The same handler the HTTP route uses, fetched per call so it sees the
bundle the lifespan wired rather than whatever existed at registration.
"""

from collections.abc import Callable
from typing import Any
from uuid import UUID

from mcp.server.fastmcp import Context, FastMCP
from pydantic import BaseModel

from keeper.execution.features.get_plan.handler import Handler
from keeper.execution.features.get_plan.query import GetPlan
from keeper.infrastructure.observability import current_correlation_id
from keeper.infrastructure.request import get_mcp_surface_id
from keeper.infrastructure.slices.principal import get_mcp_principal_id


class GetPlanOutput(BaseModel):
    """A plan as this system currently holds it."""

    plan_id: UUID
    name: str
    parameters_schema: dict[str, Any]


def register(mcp: FastMCP, *, get_handler: Callable[[], Handler]) -> None:
    """Register the tool on the given MCP server."""

    @mcp.tool(
        name="get_plan",
        description="Read a plan by id: the name it runs under and the parameters it takes.",
    )
    async def get_plan_tool(  # pyright: ignore[reportUnusedFunction]
        ctx: Context[Any, Any, Any],
        plan_id: UUID,
    ) -> GetPlanOutput:
        handler = get_handler()
        plan = await handler(
            GetPlan(plan_id=plan_id),
            principal_id=get_mcp_principal_id(ctx),
            # The tool runs inside the instrumented request that carried
            # it, so the trace context is already in scope.
            correlation_id=current_correlation_id(),
            surface_id=get_mcp_surface_id(),
        )
        return GetPlanOutput(
            plan_id=plan.id,
            name=plan.name.value,
            parameters_schema=plan.parameters_schema,
        )
