"""Register the Execution MCP tools on the shared server.

`get_handlers` is called per tool call, not at registration, so a tool
always reaches the bundle the lifespan wired rather than one captured
before startup finished.
"""

from collections.abc import Callable

from mcp.server.fastmcp import FastMCP

from keeper.execution.features.claim_execution import tool as claim_execution_tool
from keeper.execution.features.define_operation import tool as define_operation_tool
from keeper.execution.features.define_procedure import tool as define_procedure_tool
from keeper.execution.features.dispatch_execution import tool as dispatch_execution_tool
from keeper.execution.features.end_execution import tool as end_execution_tool
from keeper.execution.features.get_execution import tool as get_execution_tool
from keeper.execution.features.get_operation import tool as get_operation_tool
from keeper.execution.features.get_procedure import tool as get_procedure_tool
from keeper.execution.features.list_executions import tool as list_executions_tool
from keeper.execution.features.list_operations import tool as list_operations_tool
from keeper.execution.features.list_procedures import tool as list_procedures_tool
from keeper.execution.features.list_steps_without_datasets import (
    tool as list_steps_without_datasets_tool,
)
from keeper.execution.features.report_step import tool as report_step_tool
from keeper.execution.features.report_step_run import tool as report_step_run_tool
from keeper.execution.wire import ExecutionHandlers


def register_execution_tools(
    mcp: FastMCP,
    *,
    get_handlers: Callable[[], ExecutionHandlers],
) -> None:
    """Register every Execution slice's MCP tool."""
    define_operation_tool.register(
        mcp,
        get_handler=lambda: get_handlers().define_operation,
    )
    get_operation_tool.register(
        mcp,
        get_handler=lambda: get_handlers().get_operation,
    )
    list_operations_tool.register(
        mcp,
        get_handler=lambda: get_handlers().list_operations,
    )
    define_procedure_tool.register(
        mcp,
        get_handler=lambda: get_handlers().define_procedure,
    )
    get_procedure_tool.register(
        mcp,
        get_handler=lambda: get_handlers().get_procedure,
    )
    list_procedures_tool.register(
        mcp,
        get_handler=lambda: get_handlers().list_procedures,
    )
    dispatch_execution_tool.register(
        mcp,
        get_handler=lambda: get_handlers().dispatch_execution,
    )
    claim_execution_tool.register(
        mcp,
        get_handler=lambda: get_handlers().claim_execution,
    )
    report_step_tool.register(
        mcp,
        get_handler=lambda: get_handlers().report_step,
    )
    report_step_run_tool.register(
        mcp,
        get_handler=lambda: get_handlers().report_step_run,
    )
    end_execution_tool.register(
        mcp,
        get_handler=lambda: get_handlers().end_execution,
    )
    get_execution_tool.register(
        mcp,
        get_handler=lambda: get_handlers().get_execution,
    )
    list_executions_tool.register(
        mcp,
        get_handler=lambda: get_handlers().list_executions,
    )
    list_steps_without_datasets_tool.register(
        mcp,
        get_handler=lambda: get_handlers().list_steps_without_datasets,
    )


__all__ = ["register_execution_tools"]
