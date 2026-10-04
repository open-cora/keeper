"""The register_dataset_manifest slice, re-exported so callers read `.bind`."""

from keeper.custody.features.register_dataset_manifest.command import RegisterDatasetManifest
from keeper.custody.features.register_dataset_manifest.decider import decide
from keeper.custody.features.register_dataset_manifest.handler import Handler, bind
from keeper.custody.features.register_dataset_manifest.route import router

__all__ = [
    "Handler",
    "RegisterDatasetManifest",
    "bind",
    "decide",
    "router",
]
