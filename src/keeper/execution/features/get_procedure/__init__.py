"""The get_procedure slice, re-exported so callers read `get_procedure.bind`."""

from keeper.execution.features.get_procedure.handler import Handler, bind
from keeper.execution.features.get_procedure.query import GetProcedure
from keeper.execution.features.get_procedure.route import router

__all__ = [
    "GetProcedure",
    "Handler",
    "bind",
    "router",
]
