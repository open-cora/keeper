"""The register_dataset_address slice, re-exported so callers read `.bind`."""

from keeper.custody.features.register_dataset_address.command import RegisterDatasetAddress
from keeper.custody.features.register_dataset_address.decider import decide
from keeper.custody.features.register_dataset_address.handler import Handler, bind
from keeper.custody.features.register_dataset_address.route import router

__all__ = [
    "Handler",
    "RegisterDatasetAddress",
    "bind",
    "decide",
    "router",
]
