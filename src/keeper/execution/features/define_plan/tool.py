"""MCP door for defining a plan.

The same handler the HTTP route uses. The handler is fetched per call
rather than at registration, so it sees the bundle the lifespan wired
rather than whatever existed when the server was built.

No idempotency key. MCP has no client-supplied retry tag to carry one,
so the wrapped handler is called with None and behaves as the bare one.
"""

from collections.abc import Callable
from typing import Any
from uuid import UUID

from mcp.server.fastmcp import Context, FastMCP
from pydantic import BaseModel

from keeper.execution.features.define_plan.command import DefinePlan
from keeper.execution.features.define_plan.handler import IdempotentHandler
from keeper.infrastructure.observability import current_correlation_id
from keeper.infrastructure.request import get_mcp_surface_id
from keeper.infrastructure.slices.principal import get_mcp_principal_id


class DefinePlanOutput(BaseModel):
    """What the tool hands back."""

    plan_id: UUID


def register(mcp: FastMCP, *, get_handler: Callable[[], IdempotentHandler]) -> None:
    """Register the tool on the given MCP server."""

    @mcp.tool(
        name="define_plan",
        description=(
            "Define a runnable plan by name, with a JSON Schema for the "
            "parameters a run of it must supply, and return its id."
        ),
    )
    async def define_plan_tool(  # pyright: ignore[reportUnusedFunction]
        ctx: Context[Any, Any, Any],
        name: str,
        parameters_schema: dict[str, Any],
    ) -> DefinePlanOutput:
        handler = get_handler()
        plan_id = await handler(
            DefinePlan(name=name, parameters_schema=parameters_schema),
            principal_id=get_mcp_principal_id(ctx),
            # The tool runs inside the instrumented request that carried
            # it, so the trace context is already in scope.
            correlation_id=current_correlation_id(),
            surface_id=get_mcp_surface_id(),
        )
        return DefinePlanOutput(plan_id=plan_id)
