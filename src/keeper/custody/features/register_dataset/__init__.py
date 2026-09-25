"""The register_dataset slice, re-exported so callers read `.bind`."""

from keeper.custody.features.register_dataset.command import RegisterDataset
from keeper.custody.features.register_dataset.decider import decide
from keeper.custody.features.register_dataset.handler import (
    Handler,
    IdempotentHandler,
    bind,
)
from keeper.custody.features.register_dataset.route import router

__all__ = [
    "Handler",
    "IdempotentHandler",
    "RegisterDataset",
    "bind",
    "decide",
    "router",
]
